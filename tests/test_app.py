import io
import json
import sqlite3
import pytest
from app import create_app, evidence, extract_file, readonly_query


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test-only", "DATA_DIR": str(tmp_path),
                       "STREAM_FACTORY": lambda _: iter(["Paris [S1]"])})


def setup(client):
    client.get("/")
    with client.session_transaction() as session:
        headers = {"X-CSRF-Token": session["csrf"]}
    cid = client.post("/api/conversations", headers=headers).json["id"]
    return f"/api/conversations/{cid}", headers


def test_persistence_and_isolation(app):
    c = app.test_client(); url, h = setup(c)
    c.post(url + "/chat", json={"message": "Bonjour"}, headers=h).get_data()
    assert len(c.get(url).json["messages"]) == 2
    other = app.test_client(); other.get("/")
    assert other.get(url).status_code == 404
    new = c.post("/api/conversations", headers=h).json["id"]
    assert c.get(f"/api/conversations/{new}").json["messages"] == []
    assert len(c.get("/api/conversations").json) == 2
    restarted = create_app(dict(app.config)).test_client()
    # Same signed browser cookie remains valid after app recreation.
    restarted.set_cookie("session", c.get_cookie("session").value)
    assert len(restarted.get(url).json["messages"]) == 2


def test_csrf_and_bad_input(app):
    c = app.test_client(); url, h = setup(c)
    assert c.post("/api/conversations").status_code == 403
    assert c.post(url + "/chat", json={"message": ""}, headers=h).status_code == 400
    for name, data in [("evil.html", b"<script>"), ("fake.pdf", b"not pdf"), ("bad.txt", b"\xff")]:
        assert c.post(url + "/upload", data={"file": (io.BytesIO(data), name)}, headers=h).status_code == 400
    assert c.post(url + "/upload", data={"file": (io.BytesIO(b"x" * (8 * 1024 * 1024 + 1)), "large.txt")}, headers=h).status_code in {400, 413}


def test_stream_sources_exports(app):
    c = app.test_client(); url, h = setup(c)
    assert c.post(url + "/upload", data={"file": (io.BytesIO("Paris est en France.".encode()), "source.txt")}, headers=h).status_code == 201
    stream = c.post(url + "/chat", json={"message": "Paris ?"}, headers=h).get_data(as_text=True)
    assert "event: done" in stream and "event: delta" in stream
    last = c.get(url).json["messages"][-1]
    assert last["meta"]["evaluation"]["citations_valides"] == ["S1"]
    assert last["meta"]["sources"][0]["location"] == "ligne 1"
    for fmt in ("txt", "md", "pdf"):
        response = c.get(url + "/export/" + fmt)
        assert response.status_code == 200
        assert response.data.startswith(b"%PDF") if fmt == "pdf" else b"Paris" in response.data
    assert c.get(url + "/summary.pdf").data.startswith(b"%PDF")


def test_partial_failure(app):
    def broken(_):
        yield "début"
        raise RuntimeError("SECRET must not leak")
    app.config["STREAM_FACTORY"] = broken
    c = app.test_client(); url, h = setup(c)
    stream = c.post(url + "/chat", json={"message": "test"}, headers=h).get_data(as_text=True)
    assert "event: error" in stream and "SECRET" not in stream
    last = c.get(url).json["messages"][-1]
    assert last["status"] == "interrupted" and last["content"] == "début"
    # Lock released after failure.
    assert c.post(url + "/chat", json={"message": "encore"}, headers=h).status_code == 200


def test_evidence_is_not_confidence():
    assert evidence("invention [S99]", []) ["citations_invalides"] == ["S99"]
    assert "absence de preuve" in evidence("réponse", []) ["statut"]


def test_sql_security(tmp_path):
    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(name TEXT)")
        db.execute("INSERT INTO items VALUES(?)", ("safe",))
    assert readonly_query(path, "SELECT * FROM items")["rows"] == [("safe",)]
    for sql in ["DELETE FROM items", "SELECT 1; DROP TABLE items", "ATTACH DATABASE ':memory:' AS x", "SELECT load_extension('x')", "WITH x AS (SELECT 1) DELETE FROM items", "PRAGMA writable_schema=ON"]:
        with pytest.raises((ValueError, sqlite3.Error)):
            readonly_query(path, sql)
    assert readonly_query(path, "SELECT count(*) FROM items")["rows"] == [(1,)]


def test_csv_xlsx_pdf():
    from openpyxl import Workbook
    from app import pdf_bytes
    assert extract_file("a.csv", b"name,total\nAlice,10")[1][0] == "ligne CSV 2"
    out = io.BytesIO(); book = Workbook(); book.active.append(["Alice", 10]); book.save(out)
    assert "Alice" in extract_file("a.xlsx", out.getvalue())[0][1]
    assert "Bonjour" in extract_file("a.pdf", pdf_bytes("Bonjour"))[0][1]


@pytest.mark.parametrize("kind", ["quota", "auth", "connection", "timeout", "empty", "missing_key"])
def test_provider_errors(app, kind):
    import httpx
    from groq import RateLimitError, APIStatusError, APIConnectionError, APITimeoutError
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    def failed(_):
        if kind == "quota":
            raise RateLimitError("private", response=httpx.Response(429, request=req), body=None)
        if kind == "auth":
            raise APIStatusError("private", response=httpx.Response(401, request=req), body=None)
        if kind == "connection":
            raise APIConnectionError(request=req)
        if kind == "timeout":
            raise APITimeoutError(request=req)
        return iter([])
    app.config["STREAM_FACTORY"] = None if kind == "missing_key" else failed
    app.config["GROQ_API_KEY"] = None
    c = app.test_client(); url, h = setup(c)
    stream = c.post(url + "/chat", json={"message": "test"}, headers=h).get_data(as_text=True)
    assert "event: error" in stream and "event: done" in stream and "private" not in stream
    assert c.get(url).json["messages"][-1]["status"] == "interrupted"


def test_disconnect_persists_partial_and_unlocks(app):
    app.config["STREAM_FACTORY"] = lambda _: iter(["partiel", "suite"])
    c = app.test_client(); url, h = setup(c)
    response = c.post(url + "/chat", json={"message": "test"}, headers=h, buffered=False)
    frames = iter(response.response)
    assert b"sources" in next(frames)
    assert b"partiel" in next(frames)
    response.close()
    last = c.get(url).json["messages"][-1]
    assert last["content"] == "partiel" and last["status"] == "interrupted"
    assert c.post(url + "/chat", json={"message": "suite"}, headers=h).get_data()


def test_database_endpoint_and_invalid_json(app, tmp_path):
    path = tmp_path / "analysis.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE ventes(montant INTEGER)")
        db.executemany("INSERT INTO ventes VALUES(?)", [(10,), (20,)])
    app.config["ANALYSIS_SQLITE_PATH"] = str(path)
    c = app.test_client(); url, h = setup(c)
    assert c.post(url + "/chat", json=[], headers=h).status_code == 400
    result = c.post(url + "/database", json={"sql": "SELECT SUM(montant) FROM ventes"}, headers=h)
    assert result.json["rows"] == [[30]]
    assert c.get(url).json["documents"][0]["name"] == "Résultat SQLite"
    assert c.get(url + "/summary.pdf").status_code == 400
