"""
Parental Waiver 文案与版本号（客户报名 Book Now 门禁）。
改文案时务必升 VERSION，以便订单存证可区分同意的是哪一版。
"""

VERSION = '2026-08-parental-v1'

TITLE = 'Parental Waiver, Release of Liability, Indemnification, and Consent Form'

# 分段便于模板渲染；与客户提供的 DOCX 对齐（无签名块）
SECTIONS = [
    {
        'heading': None,
        'paragraphs': [
            (
                'I, the undersigned, as the parent or legal guardian of the student named below, '
                'hereby give my full consent and approval for my child to participate in the Immersion '
                'Trip organized by ORIENTAL VISION & ART EDUCATION INC. D. B. A Nexus Horizons Tours, Inc. '
                '(the “Company”).'
            ),
            (
                'I acknowledge that the Trip is arranged by the Company in accordance with the itinerary '
                'agreed upon with the school. I understand that the Company assumes no responsibility for '
                'activities or travel outside the official itinerary, including but not limited to travel '
                'to and from the trip destination by bus, train, or flight.'
            ),
            (
                'I further acknowledge that travel involves inherent risks, including but not limited to '
                'illness, accidents, weather, lodging, food and drink, crime, and other unforeseen '
                'circumstances. I voluntarily accept and assume all such risks on behalf of my child, '
                'including the risk of serious injury or death.'
            ),
        ],
    },
    {
        'heading': 'Waiver and Release of Liability',
        'paragraphs': [
            'In consideration for my child’s participation in the Trip:',
            (
                'On behalf of myself and my child, I voluntarily elect to accept and assume all risks '
                'of injury or harm that may arise during travel.'
            ),
            (
                'I waive, release, discharge, and agree not to sue the Company, its officers, employees, '
                'agents, or any affiliated entities (the “Released Parties”) for any claims, damages, '
                'costs (including attorney’s fees), or causes of action, known or unknown, arising from '
                'my child’s participation in the Trip. This includes claims related to negligence, breach '
                'of contract, or wrongful conduct by the Released Parties.'
            ),
        ],
    },
    {
        'heading': 'Medical Fitness',
        'paragraphs': [
            (
                'I certify that my child is physically and mentally fit to participate in the Trip and '
                'has no health conditions that would limit participation, except as disclosed to the '
                'Company during the registration process.'
            ),
        ],
    },
    {
        'heading': 'Indemnification',
        'paragraphs': [
            (
                'I agree, on behalf of myself and my child, to indemnify, defend, and hold harmless the '
                'Released Parties from any and all claims, damages, liabilities, costs (including '
                'attorney’s fees), or causes of action brought by or on behalf of my child, even if '
                'caused in whole or in part by the negligence or wrongful conduct of the Released Parties.'
            ),
        ],
    },
    {
        'heading': 'Food Allergies Release',
        'paragraphs': [
            (
                'I acknowledge that an allergen-free environment cannot be guaranteed on the Trip. While '
                'reasonable efforts will be made to provide safe meals, food may be prepared in facilities '
                'using nuts, soy, wheat, and other allergens.'
            ),
            (
                'I accept that the Released Parties cannot guarantee that any food will be free from '
                'allergens or prevent exposure to allergens. I therefore release the Released Parties '
                'from all liability for any allergic reaction or injury that may occur.'
            ),
        ],
    },
    {
        'heading': 'Prohibition of Alcohol, Smoking, and Vaping',
        'paragraphs': [
            (
                'By agreeing to this form, I acknowledge and agree that the student traveler may not '
                'consume alcohol, smoke, or vape at any time during the Trip.'
            ),
            (
                'As parent/guardian, I understand that failure to comply with this rule may result in '
                'my child being dismissed from the Trip and sent home at my expense.'
            ),
            (
                'As student traveler, I agree to follow this rule and understand that failure to comply '
                'may result in dismissal from the Trip at my parent/guardian’s expense.'
            ),
        ],
    },
    {
        'heading': 'Acknowledgment',
        'paragraphs': [
            (
                'I confirm that I have read and fully understand this Waiver, Release of Liability, '
                'Indemnification, and Consent Form, and that it shall be binding upon me, my child, '
                'and our heirs, executors, and assigns.'
            ),
        ],
    },
]


CHECKBOX_LABEL = (
    'I have read and agree to the Parental Waiver, Release of Liability, '
    'Indemnification, and Consent Form.'
)


def is_valid_acceptance(payload):
    """校验报名 payload 中的 parental_waiver 块。"""
    if not isinstance(payload, dict):
        return False
    if not payload.get('accepted'):
        return False
    version = (payload.get('version') or '').strip()
    return version == VERSION
