from fastapi.testclient import TestClient

from app.main import app


def test_validation_error_does_not_echo_submitted_values():
    sensitive = "98765432109"
    response = TestClient(app).post("/citizen/activate/request", data={"unexpected": sensitive})
    assert response.status_code == 400
    assert sensitive not in response.text
    assert response.json()["error"] == "INVALID_REQUEST"
