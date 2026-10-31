"""Accounts for people who sign in with Google (via Streamlit's st.login).

Google proves who the person is; this module maps their permanent Google account ID to a
local account, creating it on first sign-in.
"""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from sports_info.store import repo
from sports_info.store.migrate import claim_legacy_data
from sports_info.store.models import User


def sign_in(session: Session, google_sub: str, email: str | None = None, name: str | None = None) -> User:
    """The account for this Google account, created on first sign-in. Email and name are kept current."""
    if not google_sub:
        raise ValueError("google_sub is required")
    user = repo.get_user_by_google_sub(session, google_sub)
    if user is None:
        try:
            user = repo.create_user(session, google_sub, email, name)
        except IntegrityError:
            # The same person signed in from two tabs at once and the other one created the account first.
            session.rollback()
            return repo.get_user_by_google_sub(session, google_sub)
        if repo.count_users(session) == 1:
            # The first account inherits any setup from before accounts existed.
            claim_legacy_data(session, user.id)
    elif (user.email, user.name) != (email, name):
        user.email, user.name = email, name
        session.add(user)
        session.commit()
    return user
