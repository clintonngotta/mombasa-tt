import unicodedata

from rest_framework import serializers

from .models import Country

# ISO 3166-1 alpha-2 and XK, the user-assigned code used by the location picker.
COUNTRY_CODES = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV
    BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES
    ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE
    IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY
    MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU
    NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM
    SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE
    VG VI VN VU WF WS XK YE YT ZA ZM ZW
    """.split()
)


def normalize_place(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


class CountryField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data).upper()
        if value and value not in COUNTRY_CODES:
            if len(value) != 2 or not value.isascii() or not value.isalpha() or not Country.objects.filter(pk=value).exists():
                raise serializers.ValidationError("Choose a country.")
        return value


def validate_location(attrs, instance=None, *, city_field="city", legacy_town=False):
    """Keep the country, region and city together when creating or editing a location."""
    names = ("country", "region", city_field)
    if not any(field in attrs for field in names):
        return
    for field in ("region", city_field):
        if field in attrs:
            attrs[field] = normalize_place(attrs[field])
    location = {field: attrs.get(field, getattr(instance, field, "")) for field in names}
    if not any(location.values()) or (legacy_town and not (location["country"] or location["region"])):
        return
    labels = {"country": "country", "region": "region", city_field: "city"}
    missing = {field: f"Choose a {labels[field]}." for field, value in location.items() if not value}
    if missing:
        raise serializers.ValidationError(missing)
