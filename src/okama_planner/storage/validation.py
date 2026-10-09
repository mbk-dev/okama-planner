"""Validation at the registry boundary; machine identifiers stay language-neutral."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

# ISO 3166-1 alpha-2 assigned country codes (not user-facing labels).
COUNTRIES = frozenset(
    """AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP
KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY
MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY
QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ
VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW""".split()
)
CHANNEL_FIELDS = {
    "email": "email",
    "phone": "phone",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "max": "max_messenger",
}


class ClientDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1)
    sex: Literal["female", "male"] | None = None
    birth_year: StrictInt | None = Field(default=None, ge=1, le=9999)
    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    telegram_id: StrictInt | None = Field(default=None, ge=1, le=9223372036854775807)
    whatsapp: str | None = None
    max_messenger: str | None = None
    brokers: list[str] | None = None
    primary_channel: Literal["email", "phone", "telegram", "whatsapp", "max"] | None = None
    ips_sent_at: date | None = None
    note: str | None = None

    @field_validator("full_name", "email", "phone", "telegram", "whatsapp", "max_messenger")
    @classmethod
    def nonempty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("A recorded name/contact must not be empty")
        return value

    @field_validator("brokers")
    @classmethod
    def valid_brokers(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not broker.strip() for broker in value):
            raise ValueError("Broker names must not be empty")
        return value

    @model_validator(mode="after")
    def valid_contact(self) -> Self:
        if self.primary_channel is not None and not getattr(self, CHANNEL_FIELDS[self.primary_channel]):
            raise ValueError("Primary channel requires a recorded contact")
        return self


class ResidencyDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: StrictInt = Field(ge=1, le=9999)
    country: str
    note: str | None = None

    @field_validator("country")
    @classmethod
    def valid_country(cls, value: str) -> str:
        country = value.upper()
        if country not in COUNTRIES:
            raise ValueError("Country must be an assigned ISO 3166-1 alpha-2 code")
        return country
