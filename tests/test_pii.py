from app.pii import redact_messages, redact_text
from app.schemas import Message


def test_email_is_masked():
    text, counts = redact_text("write to rahul.sharma@gmail.com today")
    assert text == "write to [EMAIL] today"
    assert counts["EMAIL"] == 1


def test_valid_card_number_is_masked():
    text, counts = redact_text("card 4111 1111 1111 1111 was charged")
    assert text == "card [CARD_NUMBER] was charged"
    assert counts["CARD_NUMBER"] == 1


def test_number_failing_luhn_is_not_a_card():
    text, counts = redact_text("ref 1234 5678 9012 3456")
    assert text == "ref 1234 5678 9012 3456"
    assert not counts


def test_ssn_is_masked():
    text, counts = redact_text("SSN 123-45-6789 on file")
    assert text == "SSN [SSN] on file"
    assert counts["SSN"] == 1


def test_phone_number_is_masked():
    text, counts = redact_text("call +91 98765 43210 now")
    assert text == "call [PHONE] now"
    assert counts["PHONE"] == 1


def test_short_numbers_are_left_alone():
    text, counts = redact_text("Order 12345 shipped")
    assert text == "Order 12345 shipped"
    assert not counts


def test_clean_text_is_unchanged():
    text, counts = redact_text("Explain DNS in one sentence.")
    assert text == "Explain DNS in one sentence."
    assert not counts


def test_all_roles_are_redacted_and_originals_untouched():
    original = [
        Message(role="system", content="Admin is root@corp.com"),
        Message(role="user", content="mail me at me@x.io"),
        Message(role="assistant", content="sure, me@x.io"),
    ]
    cleaned, counts = redact_messages(original)
    assert [m.content for m in cleaned] == [
        "Admin is [EMAIL]",
        "mail me at [EMAIL]",
        "sure, [EMAIL]",
    ]
    assert counts["EMAIL"] == 3
    assert original[1].content == "mail me at me@x.io"
