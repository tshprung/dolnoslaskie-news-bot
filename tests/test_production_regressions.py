from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import sqlite3

import pytest

import database
import digest
import freshness
from scrape_sources import extract_walbrzych24_items
from source_metrics import init_metrics,record_check,source_due,event
from summarize import _looks_like_polish_prose


@pytest.mark.parametrize('text',[
    'Wrocław and Świdnica will receive new funding from the Dolnośląskie government.',
    'The hospital in Brochów has announced changes for residents of Wrocław.',
    'New services will connect Jelenia Góra, Wałbrzych and Świdnica.',
])
def test_english_with_polish_names_is_not_rejected(text):
    assert not _looks_like_polish_prose(text)


def test_polish_prose_still_detected():
    assert _looks_like_polish_prose('Radny będzie gościem Radia Wrocław, gdzie omówi kwestie zwierząt w miastach.')


def test_walbrzych_new_layout_and_offsite_links():
    text='''<a href="/pl/11_wiadomosci/54919_darmowe-autobusy.html">Nowy rozkład i darmowe autobusy</a>
    <a href="https://evil.example/pl/11_wiadomosci/123_test.html">Nie jest artykułem tego źródła</a>'''
    items=extract_walbrzych24_items(text)
    assert len(items)==1
    assert items[0].url=='https://walbrzych24.com/pl/11_wiadomosci/54919_darmowe-autobusy.html'


def test_blocked_source_backoff_and_funnel_are_persistent():
    conn=sqlite3.connect(':memory:')
    init_metrics(conn)
    record_check(conn,'https://example.com/rss',blocked=True,error='HTTPError')
    assert not source_due(conn,'https://example.com/rss')
    conn.execute('UPDATE source_checks SET checked_at=checked_at-86401')
    assert source_due(conn,'https://example.com/rss')
    article={'id':'a','link':'https://example.com/a','source':'Source'}
    event(conn,article,'candidate')
    event(conn,article,'candidate')
    assert conn.execute('SELECT count(*) FROM candidate_events').fetchone()[0]==1
    conn.close()


def incident_row():
    return ('a','Collision blocks A4 motorway','A collision has blocked the motorway.',
            'https://example.com/a','Source','27.10.2026 10:00',int(datetime.now(timezone.utc).timestamp()))


@pytest.fixture
def conn():
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE bot_kv(k TEXT PRIMARY KEY,v TEXT)')
    digest.init_digest_db(db)
    row=incident_row()
    db.execute('INSERT INTO digest_articles(id,title,summary_en,url,source,article_date,sort_epoch) VALUES(?,?,?,?,?,?,?)',row)
    db.commit()
    yield db
    db.close()


def client_response(content):
    client=MagicMock()
    client.with_options.return_value=client
    client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return client


def test_resolved_incident_expires_without_entering_published_history(conn,monkeypatch):
    monkeypatch.setattr(freshness,'fetch_article_body',lambda *_a:('Latest update: all motorway lanes reopened at 17:45. '*4,None))
    rows=freshness.refresh_incidents(conn,client_response('{"status":"resolved","summary":"Road reopened."}'),None,(1,2),[incident_row()])
    assert rows==[]
    assert conn.execute('SELECT status,digested_at FROM digest_articles').fetchone()==('expired',None)


@pytest.mark.parametrize('content',['{"status":"unknown","summary":""}','not JSON'])
def test_uncertain_incident_is_held_pending(conn,monkeypatch,content):
    monkeypatch.setattr(freshness,'fetch_article_body',lambda *_a:('An old report says disruption may last one hour. '*4,None))
    assert freshness.refresh_incidents(conn,client_response(content),None,(1,2),[incident_row()])==[]
    assert conn.execute('SELECT status FROM digest_articles').fetchone()[0]=='pending'


def test_verification_fetch_failure_does_not_send_cached_alert(conn,monkeypatch):
    monkeypatch.setattr(freshness,'fetch_article_body',lambda *_a:('', 'fetch blocked'))
    client=MagicMock()
    assert freshness.refresh_incidents(conn,client,None,(1,2),[incident_row()])==[]
    client.chat.completions.create.assert_not_called()


def test_verified_active_incident_replaces_cached_advice(conn,monkeypatch):
    monkeypatch.setattr(freshness,'fetch_article_body',lambda *_a:('Current update: work continues until midnight. '*4,None))
    summary='The A4 remains closed until midnight while recovery work continues.'
    rows=freshness.refresh_incidents(conn,client_response('{"status":"active","summary":"'+summary+'"}'),None,(1,2),[incident_row()])
    assert rows[0][2]==summary
    assert conn.execute('SELECT summary_en FROM digest_articles').fetchone()[0]==summary


def test_superseded_reporting_is_removed():
    body='Aktualizacja godz. 18:21: droga otwarta. Aktualizacja godz. 17:18: nadal zamknięta. Wcześniej pisaliśmy: kolizja.'
    latest=freshness.latest_reporting(body)
    assert 'otwarta' in latest
    assert 'zamknięta' not in latest


def test_listing_limit_is_per_source(monkeypatch,tmp_path):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'test.db')
    db=database.init_db()
    monkeypatch.setattr(database,'SCRAPE_SOURCES',[{'key':'24wroclaw','list_url':'https://24wroclaw.pl/'},{'key':'walbrzych24','list_url':'https://walbrzych24.com/'}])
    monkeypatch.setattr(database,'SCRAPE_SOURCES_MAX_NEW_URLS',1)
    monkeypatch.setattr(database,'SCRAPE_SOURCES_MIN_INTERVAL_SEC',0)
    monkeypatch.setattr(database,'fetch_listing_html',lambda *_a:'<a href="/artykul/123/news">Important regional public service news</a>')
    monkeypatch.setattr(database,'article_html_fetch_published_utc',lambda *_a:datetime.now(timezone.utc))
    monkeypatch.setattr(database.time,'sleep',lambda *_a:None)
    rows=database._scrape_listing_sources(db,MagicMock(),(1,2),datetime.now(timezone.utc),set())
    assert len(rows)==2
    db.close()


def test_verification_dry_run_leaves_database_unchanged(conn,monkeypatch):
    monkeypatch.setattr(freshness,'fetch_article_body',lambda *_a:('Latest report: all lanes have reopened. '*5,None))
    freshness.refresh_incidents(conn,client_response('{"status":"resolved","summary":""}'),None,(1,2),[incident_row()],dry_run=True)
    assert conn.execute('SELECT status FROM digest_articles').fetchone()[0]=='pending'
