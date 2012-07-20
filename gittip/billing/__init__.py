"""This module encapsulates billing logic and db access.

There are two pieces of information for each customer related to billing:

    balanced_account_uri    NULL - This customer has never been billed.
                            'deadbeef' - This customer's card has been
                                validated and associated with a Balanced
                                account.
    last_bill_result        NULL - This customer has not been billed yet.
                            '' - This customer is in good standing.
                            <message> - An error message.

"""
from __future__ import unicode_literals

import balanced
from aspen.utils import typecheck
from gittip import db


def associate(participant_id, balanced_account_uri, card_uri):
    """Given three unicodes, return a dict.

    This function attempts to associate the credit card details referenced by
    card_uri with a Balanced Account. If the attempt succeeds we cancel the
    transaction. If it fails we log the failure. Even for failure we keep the
    balanced_account_uri, we don't reset it to None/NULL. It's useful for
    loading the previous (bad) credit card info from Balanced in order to
    prepopulate the form.

    """
    typecheck( participant_id, unicode
             , balanced_account_uri, (unicode, None)
             , card_uri, unicode
              )


    # Load or create a Balanced Account.
    # ==================================

    email_address = '{}@gittip.com'.format(participant_id)
    if balanced_account_uri is None:
        # arg - balanced requires an email address
        try:
            customer = \
               balanced.Account.query.filter(email_address=email_address).one()
        except balanced.exc.NoResultFound:
            customer = balanced.Account(email_address=email_address).save()
        CUSTOMER = """\
                
                UPDATE participants 
                   SET balanced_account_uri=%s
                 WHERE id=%s
                
        """
        db.execute(CUSTOMER, (customer.uri, participant_id))
        customer.meta['participant_id'] = participant_id
        customer.save()  # HTTP call under here
    else:
        customer = balanced.Account.find(balanced_account_uri)


    # Associate the card with the customer.
    # =====================================
    # Handle errors. Return a unicode, a simple error message. If empty it
    # means there was no error. Yay! Store any error message from the
    # Balanced API as a string in last_bill_result. That may be helpful for
    # debugging at some point.

    customer.card_uri = card_uri
    try:
        customer.save()
    except balanced.exc.HTTPError as err:
        last_bill_result = err.message
        typecheck(last_bill_result, unicode)
        out = err.message
    else:
        out = last_bill_result = ''
        
    STANDING = """\

        UPDATE participants
           SET last_bill_result=%s 
         WHERE id=%s

    """
    db.execute(STANDING, (last_bill_result, participant_id))
    return out


def clear(participant_id, balanced_account_uri):
    typecheck(participant_id, unicode, balanced_account_uri, unicode)

    # accounts in balanced cannot be deleted at the moment. instead we mark all
    # valid cards as invalid which will restrict against anyone being able to
    # issue charges against them in the future.
    customer = balanced.Account.find(balanced_account_uri)
    for card in customer.cards:
        if card.is_valid:
            card.is_valid = False
            card.save()

    CLEAR = """\

        UPDATE participants
           SET balanced_account_uri=NULL
             , last_bill_result=NULL
         WHERE id=%s

    """
    db.execute(CLEAR, (participant_id,))


# Account
# =======

class Account(object):
    """This is a dict-like wrapper around a Balanced Account.
    """

    _account = None  # underlying balanced.Account object

    def __init__(self, balanced_account_uri):
        """Given a Balanced account_uri, load data from Balanced.
        """
        if balanced_account_uri is not None:
            self._account = balanced.Account.find(balanced_account_uri)

    def _get(self, name):
        """Given a name, return a unicode.
        """
        out = ""
        if self._account is not None:
            try:
                # this is an abortion
                # https://github.com/balanced/balanced-python/issues/3
                cards = self._account.cards
                cards = sorted(cards, key=lambda c: c.created_at)
                cards.reverse()
                card = cards[0]
                out = getattr(card, name, "")
            except IndexError:  # no cards associated
                pass
            if out is None:
                out = ""
        return out

    def __getitem__(self, name):
        """Given a name, return a string.
        """
        if name == 'id':
            out = self._account.uri if self._account is not None else None
        elif name == 'last4':
            out = self._get('last_four')
            if out:
                out = "************" + out
        elif name == 'expiry':
            month = self._get('expiration_month')
            year = self._get('expiration_year')

            if month and year:
                out = "%d/%d" % (month, year)
            else:
                out = ""
        else:
            out = self._get(name)
        return out
