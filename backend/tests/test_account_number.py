"""Account-number generation (audit C1's neighborhood).

_next_account_number needs Postgres nextval(), so the session is stubbed;
what's verified is the formatting AND that the statement really is the
sequence call (the C1 NameError lived exactly here).
"""

from sqlalchemy.dialects import postgresql

from app.modules.core import service


class _StubSession:
    def __init__(self, value: int) -> None:
        self.value = value
        self.statement = None

    def scalar(self, statement):  # noqa: ANN001, ANN202
        self.statement = statement
        return self.value


def test_account_number_format():
    assert service._next_account_number(_StubSession(1)) == "TV-000001"
    assert service._next_account_number(_StubSession(42)) == "TV-000042"


def test_account_number_grows_past_six_digits():
    assert service._next_account_number(_StubSession(1234567)) == "TV-1234567"


def test_account_number_uses_the_sequence():
    stub = _StubSession(7)
    service._next_account_number(stub)
    sql = str(
        stub.statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "nextval" in sql
    assert "account_number_seq" in sql
