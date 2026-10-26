import io
import json
import sqlite3
from pathlib import Path

import pytest
from pypdf import PdfReader

from app import create_app
from governance import profile_table, validate_rules


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "features-test", "DATA_DIR": str(tmp_path),
                       "STREAM_FACTORY": lambda _: iter(["Une réponse [S1].", {"usage": {"prompt_tokens": 40, "completion_tokens": 6, "total_tokens": 46}}])})


def setup(client):
    client.get("/")
    with client.session_transaction() as s:
        h = {"X-CSRF-Token": s["csrf"]}
    cid = client.post("/api/conversations", headers=h).json["id"]
    return f"/api/conversations/{cid}", h


def ask(c, url, h, text="Question"):
    response = c.post(url + "/chat", json={"message": text}, headers=h)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def import_csv(c, url, h, data=b"nom,age\nAlice,10\nAlice,10\nBob,\nClaire,inconnu\nDavid,300\n"):
    r = c.post(url + "/datasets", data={"file": (io.BytesIO(data), "clients.csv")}, headers=h)
    assert r.status_code == 201, r.json
    return r.json


def test_domains_sources_scope_and_limits(app):
    captured = []
    def provider(messages):
        captured.append(messages)
        yield "Preuve confidentielle [S1]"
    app.config["STREAM_FACTORY"] = provider
    c = app.test_client(); url, h = setup(c)
    assert c.patch(url, json={"domain": "finance"}, headers=h).status_code == 200
    for domain in ["bad", [], None]:
        assert c.patch(url, json={"domain": domain}, headers=h).status_code == 400
    did = c.post(url + "/upload", data={"file": (io.BytesIO(b"Confidentiel\nAutre passage\nTroisieme"), "preuve.txt")}, headers=h).json["id"]
    assert c.patch(url + f"/sources/{did}", json={"excerpt_count": 1, "unit": "lines"}, headers=h).status_code == 200
    ask(c, url, h)
    first = c.get(url).json["messages"][-1]
    assert len(first["meta"]["sources"]) == 1
    assert "Domaine finance" in captured[-1][0]["content"]
    assert c.patch(url + f"/sources/{did}", json={"enabled": False}, headers=h).status_code == 200
    ask(c, url, h)
    assert c.get(url).json["messages"][-1]["meta"]["sources"] == []
    assert "Confidentiel" not in json.dumps(captured[-1])
    assert "Preuve confidentielle" not in json.dumps(captured[-1])
    for payload in [{"excerpt_count": 0}, {"excerpt_count": True}, {"enabled": "false"}, {"unit": []}]:
        assert c.patch(url + f"/sources/{did}", json=payload, headers=h).status_code == 400


def test_performance_ratings_json_and_summary(app):
    c = app.test_client(); url, h = setup(c)
    assert c.get(url + "/summary.pdf").status_code == 400
    ask(c, url, h, "Résumer mon échange")
    data = c.get(url).json; last = data["messages"][-1]; p = last["meta"]["performance"]
    assert 0 <= p["first_token_ms"] <= p["duration_ms"]
    assert data["metrics"]["tokens_known"]["total_tokens"] == 46
    assert data["metrics"]["usage_known_requests"] == 1
    for value in [3, 2, 1, None]:
        assert c.post(url + f"/messages/{last['id']}/rating", json={"rating": value}, headers=h).status_code == 200
        assert c.get(url).json["messages"][-1]["meta"]["rating"] == value
    assert c.post(url + f"/messages/{last['id']}/rating", json={"rating": True}, headers=h).status_code == 400
    assert c.post(url + f"/messages/{data['messages'][0]['id']}/rating", json={"rating": 3}, headers=h).status_code == 404
    exported = c.get(url + "/export/json")
    assert exported.json["schema_version"] == 2 and exported.json["messages"][-1]["meta"]["performance"]["usage"]["total_tokens"] == 46
    assert "owner" not in exported.get_data(as_text=True)
    summary = c.get(url + "/summary.pdf")
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(summary.data)).pages)
    assert "conversation" in text and "mon échange" in text
    app.config["STREAM_FACTORY"] = lambda _: iter(["Sans mesure"])
    ask(c, url, h)
    stats = c.get(url).json["metrics"]
    assert stats["tokens_known"]["total_tokens"] == 46 and stats["usage_unknown_requests"] == 1


def test_csv_governance_rules_query_and_isolation(app):
    c = app.test_client(); url, h = setup(c)
    imported = import_csv(c, url, h); did = imported["id"]
    assert c.get(url).json["documents"][0]["enabled"] == 0
    report = imported["report"][0]
    assert report["rows_analyzed"] == 5 and report["missing_cells"] == 1 and report["duplicate_rows"] == 1
    assert report["type_consistency_pct"] < 100 and report["rule_compliance_pct"] is None
    rules = {"required": ["age", "email"], "types": {"age": "number"}, "ranges": {"age": {"min": 0, "max": 120}}}
    r = c.post(url + f"/datasets/{did}/profile", json={"rules": rules}, headers=h)
    assert r.status_code == 200 and r.json["report"][0]["rule_failures"] >= 4
    assert c.get(url).json["datasets"][0]["rules"] == rules
    query = c.post(url + "/database", json={"dataset_id": did, "sql": 'SELECT count(*) FROM "table_1"'}, headers=h)
    assert query.json["rows"] == [[5]]
    assert all(d["enabled"] == 0 for d in c.get(url).json["documents"])
    assert c.post(url + "/database", json={"dataset_id": did, "sql": 'DELETE FROM "table_1"'}, headers=h).status_code == 400
    other_url, other_h = setup(c)
    assert c.post(other_url + f"/datasets/{did}/profile", json={"rules": {}}, headers=other_h).status_code == 404
    assert c.post(other_url + "/database", json={"dataset_id": did, "sql": "SELECT 1"}, headers=other_h).status_code == 404


def test_sqlite_import_immutable_and_reset(app, tmp_path):
    original = tmp_path / "source.sqlite"
    with sqlite3.connect(original) as db:
        db.execute('CREATE TABLE "odd;name"(valeur REAL)')
        db.executemany('INSERT INTO "odd;name" VALUES(?)', [(10,), (10,), (10,), (10,), (900,)])
    raw = original.read_bytes()
    c = app.test_client(); url, h = setup(c)
    r = c.post(url + "/datasets", data={"file": (io.BytesIO(raw), "base.sqlite")}, headers=h)
    assert r.status_code == 201, r.json
    did = r.json["id"]; path = Path(app.config["DATA_DIR"]) / "datasets" / (did + ".sqlite3")
    assert path.read_bytes() == raw and r.json["report"][0]["columns"][0]["outliers"] == 1
    ask(c, url, h)
    new = c.post(url + "/reset", headers=h)
    assert new.status_code == 201
    assert c.get(url).status_code == 404 and not path.exists()
    assert c.get("/api/conversations/" + new.json["id"]).json["messages"] == []
    assert original.read_bytes() == raw


def test_invalid_dataset_cleanup_and_structural_issues(app):
    c = app.test_client(); url, h = setup(c)
    for name, raw in [("fake.sqlite", b"bad"), ("evil.html", b"<html>"), ("a.csv", b""), ("a.csv", b"\xff")]:
        assert c.post(url + "/datasets", data={"file": (io.BytesIO(raw), name)}, headers=h).status_code == 400
    assert not list((Path(app.config["DATA_DIR"]) / "datasets").glob("*.sqlite3"))
    imported = import_csv(c, url, h, b"name,name,\nAlice,A,1\nBob,B\n")
    assert len(imported["report"][0]["structural_issues"]) >= 3
    assert len({col["name"] for col in imported["report"][0]["columns"]}) == 3


def test_in_progress_blocks_reset_and_source_changes(app):
    c = app.test_client(); url, h = setup(c)
    with sqlite3.connect(Path(app.config["DATA_DIR"]) / "history.sqlite3") as db:
        import time
        db.execute("INSERT INTO jobs VALUES(?,?)", (url.rsplit("/", 1)[1], time.time()))
    assert c.post(url + "/reset", headers=h).status_code == 409
    assert c.patch(url, json={"domain": "finance"}, headers=h).status_code == 409
    assert c.get(url).status_code == 200


@pytest.mark.parametrize("rules", [{"bad": 1}, {"required": "age"}, {"types": {"age": "magic"}}, {"ranges": {"age": {"min": 10, "max": 1}}}, {"ranges": {"age": {"min": True}}}])
def test_bad_rules(rules):
    with pytest.raises(ValueError):
        validate_rules(rules)


def test_empty_profile_and_missing_rule_columns():
    p = profile_table("empty", ["age"], [], rules={"required": ["email"]})
    assert p["completeness_pct"] is None and p["uniqueness_pct"] is None
    assert p["rule_failures"] == 1 and p["rule_compliance_pct"] == 0


def test_migration_preserves_old_history(tmp_path):
    path = tmp_path / "history.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE conversations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL); CREATE TABLE documents(id TEXT PRIMARY KEY,cid TEXT,name TEXT,chunks TEXT);")
        db.execute("INSERT INTO conversations VALUES('old','owner','Ancienne')")
        db.execute("INSERT INTO documents VALUES('doc','old','Original','[]')")
    create_app({"TESTING": True, "SECRET_KEY": "test", "DATA_DIR": str(tmp_path)})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title,domain FROM conversations").fetchone() == ("Ancienne", "general")
        assert db.execute("SELECT enabled,excerpt_count,unit FROM documents").fetchone() == (1, 3, "excerpts")


@pytest.mark.parametrize("usage_location", ["usage", "x_groq"])
def test_groq_usage_chunk_and_sdk_request(app, monkeypatch, usage_location):
    import app as module
    import httpx
    from groq import Groq as RealGroq
    final = {"id": "reply", "created": 1, "model": "mock", "object": "chat.completion.chunk", "choices": [],
             usage_location: {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16} if usage_location == "usage" else {"usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}}}
    chunks = [{"id": "reply", "created": 1, "model": "mock", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "Bonjour"}, "finish_reason": "stop"}]}, final]
    def transport(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        assert "stream_options" not in body
        text = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)
    def client(**kwargs):
        return RealGroq(http_client=httpx.Client(transport=httpx.MockTransport(transport)), **kwargs)
    monkeypatch.setattr(module, "Groq", client)
    app.config.update(STREAM_FACTORY=None, GROQ_API_KEY="fake-test")
    c = app.test_client(); url, h = setup(c); ask(c, url, h)
    assert c.get(url).json["metrics"]["tokens_known"]["total_tokens"] == 16


def test_paragraph_and_line_source_units(app):
    c = app.test_client(); url, h = setup(c)
    text = b"Premier paragraphe\nligne suivante\n\nSecond paragraphe\nautre ligne"
    did = c.post(url + "/upload", data={"file": (io.BytesIO(text), "paragraphes.txt")}, headers=h).json["id"]
    c.patch(url + f"/sources/{did}", json={"unit": "paragraphs", "excerpt_count": 1}, headers=h)
    ask(c, url, h, "Premier paragraphe")
    assert c.get(url).json["messages"][-1]["meta"]["sources"][0]["passage"] == "Premier paragraphe\nligne suivante"
    c.patch(url + f"/sources/{did}", json={"unit": "lines", "excerpt_count": 1}, headers=h)
    ask(c, url, h, "Premier paragraphe")
    assert c.get(url).json["messages"][-1]["meta"]["sources"][0]["passage"] == "Premier paragraphe"


def test_xlsx_dataset_and_truncated_sqlite(app, tmp_path):
    from openpyxl import Workbook
    book = Workbook(); sheet = book.active
    sheet.append(['nom";DROP TABLE table_1;--', "montant"]); sheet.append(["Alice", 10]); sheet.append(["Bob", None])
    output = io.BytesIO(); book.save(output)
    c = app.test_client(); url, h = setup(c)
    result = c.post(url + "/datasets", data={"file": (io.BytesIO(output.getvalue()), "donnees.xlsx")}, headers=h)
    assert result.status_code == 201, result.json
    assert result.json["report"][0]["missing_cells"] == 1
    assert c.post(url + "/database", json={"dataset_id": result.json["id"], "sql": "SELECT count(*) FROM table_1"}, headers=h).json["rows"] == [[2]]
    path = tmp_path / "many.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE nombres(n INTEGER)")
        db.executemany("INSERT INTO nombres VALUES(?)", [(i,) for i in range(2001)])
    result = c.post(url + "/datasets", data={"file": (io.BytesIO(path.read_bytes()), "many.sqlite")}, headers=h)
    assert result.status_code == 201 and result.json["report"][0]["truncated"]
    assert result.json["report"][0]["rows_analyzed"] == 2000


@pytest.mark.parametrize("status,expected", [(404, "GROQ_MODEL"), (400, "Configuration refusée")])
def test_sdk_configuration_errors_are_actionable(app, monkeypatch, status, expected):
    import app as module
    import httpx
    from groq import Groq as RealGroq
    def transport(request):
        return httpx.Response(status, json={"error": {"message": "provider detail is private", "type": "invalid_request_error"}})
    monkeypatch.setattr(module, "Groq", lambda **kwargs: RealGroq(http_client=httpx.Client(transport=httpx.MockTransport(transport)), **kwargs))
    app.config.update(STREAM_FACTORY=None, GROQ_API_KEY="test-only")
    c = app.test_client(); url, h = setup(c)
    stream = ask(c, url, h)
    assert expected in stream and "provider detail is private" not in stream
    assert c.get(url).json["messages"][-1]["status"] == "interrupted"
