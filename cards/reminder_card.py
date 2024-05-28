import modules.preferences.preferences as pref


def accepted_body(s_date):
    body_1 = (
        f"Your current Outlook status for the upcoming FUSE session on {s_date} is: ACCEPTED. "
        f"\n\nTHANK YOU for participating and contributing to the strengthening of the best group of SAs at Cisco. "
        f"\n\nWe are excited to welcome a special guest, XXXXXXXXX. "
        f"\n\nA FUSE partner will be aligned for you, so please expect to reach out to your partner, "
        f"or for your partner to reach out to you once assigned during the session. "
        f"\n\nIf your plans change, please send an ACCEPT or DECLINE to the Outlook invite ASAP "
        f"so that the pairings can be adjusted for the day."
    )
    return body_1


def tentative_body(s_date):
    body_1 = (
        f"Your current Outlook status for the upcoming FUSE session on {s_date} is: TENTATIVE "
        f"\n\nWe sincerely hope that you can join us. We are excited to welcome a special guest, XXXXXXXX. "
        f"\n\nIf possible, please send an ACCEPT or DECLINE to the Outlook invite ASAP so that "
        f"the pairings can be determined for the day.  If you remain tentative, we will do our "
        f"best to accommodate a pairing during the session. Thank you!"
    )
    return body_1


def no_response_body(s_date):
    body_1 = (
        f"Your current Outlook status for the upcoming FUSE session on {s_date} is: NO RESPONSE "
        f"\n\nPlease send an ACCEPT or DECLINE to the Outlook invite ASAP so that the pairings can "
        f"be finalized for the day.  We are excited to welcome a special guest, XXXXXXXX. "
    )
    return body_1


def reminder_card(s_date, card_type):
    if card_type == "accepted":
        body_1 = accepted_body(s_date)
    elif card_type == "tentative":
        body_1 = tentative_body(s_date)
    elif card_type == "no_response":
        body_1 = no_response_body(s_date)

    body_2 = (
        "We are looking forward to hearing about the new SE connection you make. "
        "Thanks again, and we will see you in a couple of days!"
    )

    send_card = {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "type": "AdaptiveCard",
            "body": [
                {
                    "type": "ImageSet",
                    "images": [
                        {
                            "type": "Image",
                            "size": "Medium",
                            "url": pref.logo_url,
                            "height": "100px",
                            "width": "400px",
                        }
                    ],
                },
                {
                    "type": "Container",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": "FUSE Session RSVP Confirmation",
                            "wrap": True,
                            "horizontalAlignment": "Center",
                            "fontType": "Monospace",
                            "size": "Large",
                            "weight": "Bolder",
                        },
                        {
                            "type": "TextBlock",
                            "text": body_1,
                            "wrap": True,
                            "fontType": "Monospace",
                            "size": "Small",
                            "weight": "Bolder",
                        },
                        {
                            "type": "TextBlock",
                            "wrap": True,
                            "text": body_2,
                            "fontType": "Monospace",
                            "weight": "Bolder",
                            "size": "Small",
                        },
                    ],
                },
            ],
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.2",
        },
    }
    return send_card
