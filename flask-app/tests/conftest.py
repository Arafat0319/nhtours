import pytest

from app import create_app


@pytest.fixture(scope="session")
def app():
    application = create_app("development")
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()
