"""Per-business configuration loaded from businesses/*.yaml.

Everything business-specific lives in config: SOP text, topic keywords,
escalation categories and guardrails, customer-facing replies and the lead
qualification fields. Adding a new business is a new YAML file, no code changes.
"""

import os
import re
from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from escalation import BASE_RULES, build_rules, label_for

BUSINESS_DIR = Path(os.getenv("BUSINESS_DIR", Path(__file__).resolve().parent / "businesses"))
DEFAULT_BUSINESS_ID = os.getenv("DEFAULT_BUSINESS", "bloom")

DEFAULT_REPLIES = {
    "help": "I can help with questions about our services, prices, opening hours and booking. What would you like to know?",
    "greeting": "Hello! How can I help you today?",
    "thanks": "You're welcome! Is there anything else I can help with?",
    "not_in_sop": "I'm sorry, I don't have that information. I've noted your question so our team can follow up with you.",
    "escalation": "I'm sorry to hear that. I've passed your conversation to a member of our team, who will get back to you shortly.",
    "unanswered_limit": (
        "I'm sorry I haven't been able to answer your questions. "
        "I've passed this conversation to a member of our team, who will get back to you shortly."
    ),
    "error": (
        "Sorry, I'm having trouble answering right now. "
        "I've passed your message to our team, who will get back to you shortly."
    ),
}


class LeadField(BaseModel):
    name: str
    label: str
    question: str
    description: str = ""
    type: Literal["text", "phone", "choice"] = "text"
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _choice_needs_options(self):
        if self.type == "choice" and not self.options:
            raise ValueError(f"lead field '{self.name}' is a choice but has no options")
        return self


class LeadConfig(BaseModel):
    intro: str = "I'd be happy to help you book."
    done: str = "Our team will contact you shortly."
    fields: list[LeadField]


class CustomEscalation(BaseModel):
    label: str
    patterns: list[str]


class EscalationConfig(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: list(BASE_RULES))
    guardrails: list[str] = Field(default_factory=lambda: ["medical", "legal"])
    extra_patterns: dict[str, list[str]] = Field(default_factory=dict)
    custom: dict[str, CustomEscalation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_categories(self):
        unknown = set(self.enabled) - set(BASE_RULES)
        if unknown:
            raise ValueError(f"unknown escalation categories: {sorted(unknown)}")
        known = set(self.enabled) | set(self.custom)
        bad_guardrails = set(self.guardrails) - known
        if bad_guardrails:
            raise ValueError(f"guardrails not enabled: {sorted(bad_guardrails)}")
        return self


class BusinessConfig(BaseModel):
    id: str
    name: str
    sop: str
    theme_color: str = Field("#4a6cf7", pattern=r"^#[0-9a-fA-F]{6}$")
    topics: dict[str, list[str]]
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    replies: dict[str, str] = Field(default_factory=dict)
    lead: LeadConfig

    model_config = {"ignored_types": (cached_property,)}

    # --- derived, compiled once ---------------------------------------------------

    @cached_property
    def escalation_rules(self):
        return build_rules(
            self.escalation.enabled,
            self.escalation.extra_patterns,
            {code: spec.model_dump() for code, spec in self.escalation.custom.items()},
        )

    @cached_property
    def guardrail_categories(self):
        # Custom categories are rule-only (the classifier doesn't know them), so they
        # are always enforced as guardrails.
        return set(self.escalation.guardrails) | set(self.escalation.custom)

    @cached_property
    def topic_patterns(self):
        return {
            topic: [re.compile(rf"(?<!\w){p}(?!\w)", re.IGNORECASE) for p in patterns]
            for topic, patterns in self.topics.items()
        }

    @property
    def lead_fields(self):
        return self.lead.fields

    def lead_field(self, name):
        return next((f for f in self.lead.fields if f.name == name), None)

    def reply(self, key):
        return self.replies.get(key) or DEFAULT_REPLIES.get(key) or DEFAULT_REPLIES["escalation"]

    def escalation_reply(self, category):
        return self.replies.get(category) or DEFAULT_REPLIES.get(category) or self.reply("escalation")

    def label_for(self, category):
        return label_for(category, self.escalation_rules)

    def match_topics(self, text):
        return [t for t, pats in self.topic_patterns.items() if any(p.search(text) for p in pats)]


def load_business(path):
    with open(path, encoding="utf-8") as fh:
        return BusinessConfig.model_validate(yaml.safe_load(fh))


def load_all(directory=BUSINESS_DIR):
    businesses = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        biz = load_business(path)
        if biz.id in businesses:
            raise ValueError(f"duplicate business id '{biz.id}' in {path}")
        businesses[biz.id] = biz
    if not businesses:
        raise RuntimeError(f"no business configs found in {directory}")
    return businesses


BUSINESSES = load_all()


def get_business(business_id=None):
    """Return the business config, or raise KeyError for an unknown id."""
    return BUSINESSES[business_id or DEFAULT_BUSINESS_ID]
