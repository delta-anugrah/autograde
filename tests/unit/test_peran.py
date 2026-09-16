from palmgrade.domain.peran import (
    ROLE_OPERATOR,
    ROLE_SUPPORT,
    filter_erp_role,
    parse_allowed_roles,
    sanitize_role,
)


def test_known_role_passes_through_unchanged():
    assert sanitize_role("support") == ROLE_SUPPORT
    assert sanitize_role("operator") == ROLE_OPERATOR


def test_unknown_role_falls_back_to_operator():
    """An unrecognized value must not unlock anything."""
    for value in ("admin", "", None, 7, "developer"):
        assert sanitize_role(value) == ROLE_OPERATOR


def test_role_read_case_insensitively():
    assert sanitize_role("Support") == ROLE_SUPPORT


def test_surrounding_whitespace_is_tolerated():
    """A stray space must not silently demote a support account to operator."""
    assert sanitize_role("  support  ") == ROLE_SUPPORT
    assert sanitize_role("SUPPORT ") == ROLE_SUPPORT


def test_allow_list_read_from_env():
    assert parse_allowed_roles("support") == frozenset({"support"})
    assert parse_allowed_roles("support, operator") == frozenset({"support", "operator"})
    assert parse_allowed_roles("") == frozenset()
    assert parse_allowed_roles("   ") == frozenset()


def test_erp_role_outside_allow_list_falls_back_to_operator():
    """Factory-side brake: an empty .env means ERP cannot promote anyone."""
    assert filter_erp_role("support", frozenset()) == ROLE_OPERATOR
    assert filter_erp_role("support", frozenset({"support"})) == ROLE_SUPPORT


def test_unknown_erp_role_falls_back_even_with_a_wide_allow_list():
    assert filter_erp_role("admin", frozenset({"admin"})) == ROLE_OPERATOR
