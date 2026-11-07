"""Regressions from the November 3–6 production briefs."""
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import digest
from article_fetch import _publisher_article_body, fetch_article_body
from story_identity import story_identity
from summarize import summarize_in_english


def row(aid, title, facts, url=None):
    return (aid, title, facts, url or 'https://example.com/'+aid,
            'Regional outlet', '06.11.2026 12:00', int(datetime.now(timezone.utc).timestamp()))


def client_responses(*values):
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=value), finish_reason='stop')]) for value in values]
    return client


def test_renamed_portal_article_is_blocked_across_days_and_within_brief():
    first = row('a', 'Koniec połączenia', 'The IC Śnieżka service ends on December 13.',
                'https://www.portalsamorzadowy.pl/dolnoslaskie/old-headline,682515.html')
    renamed = row('b', 'PKP Intercity wycina pociąg', 'Direct trains to the spas end on December 13.',
                  'http://portalsamorzadowy.pl/dolnoslaskie/new-headline,682515.html?utm_source=rss')
    assert digest._remove_recent_duplicates([renamed], [first]) == []
    assert digest._deduplicate_rows([first, renamed]) == [first]
    different = row('c', 'Nowy pociąg', 'A different train opens.',
                    'https://portalsamorzadowy.pl/dolnoslaskie/news,682516.html')
    assert digest._remove_recent_duplicates([different], [first]) == [different]


def test_wordpress_post_query_ids_remain_distinct():
    assert story_identity('https://dolnyslask.pl/?p=14970') != story_identity('https://dolnyslask.pl/?p=14971')


def test_published_history_reaches_previous_week():
    conn = sqlite3.connect(':memory:')
    digest.init_digest_db(conn)
    record = row('old', 'Rail cancellation', 'The rail service will end.')
    conn.execute('INSERT INTO digest_articles(id,title,summary_en,url,source,article_date,sort_epoch,status,digested_at) '
                 "VALUES(?,?,?,?,?,?,?,'published',datetime('now','-6 days'))", record)
    assert digest._recent_digest_history(conn) == [record]
    conn.close()


def test_novelty_discards_bypass_repeat_but_keeps_reopening_and_new_warning_period():
    history = [row('old', 'Bypass opening', 'Dzierżoniów bypass opened on November 3.')]
    candidates = [
        row('bypass', 'Regional success', 'The Dzierżoniów bypass is fully open after eight years.'),
        row('aow', 'AOW reopened', 'The AOW lane has reopened after expansion-joint repairs.'),
        row('fog', 'Fog warning', 'A new fog warning applies from November 6 to November 7.'),
    ]
    client = client_responses(json.dumps({'decisions': [
        {'index': 0, 'keep': False, 'reason': 'Same bypass opening already covered'},
        {'index': 1, 'keep': True, 'reason': 'Lane reopened after the earlier restriction'},
        {'index': 2, 'keep': True, 'reason': 'Different warning validity period'},
    ]}))
    assert digest._filter_covered_events(client, candidates, history) == candidates[1:]


def test_same_brief_event_check_runs_even_without_previous_coverage():
    candidates = [row('radio', 'Ostrzeżenie IMGW', 'Fog in Lower Silesia from November 6 to November 7.'),
                  row('legnica', 'Gęste mgły', 'IMGW warns of fog in Lower Silesia from November 6 to November 7.')]
    client = client_responses(json.dumps({'decisions': [
        {'index': 0, 'keep': True, 'reason': 'New warning period, strongest practical report'},
        {'index': 1, 'keep': False, 'reason': 'Same region and validity period as candidate 0'},
    ]}))
    assert digest._filter_covered_events(client, candidates, []) == candidates[:1]


def test_explicit_warning_periods_override_inconsistent_semantic_verdicts():
    history = [row('yesterday', 'Fog warning', 'IMGW issued a fog warning for Lower Silesia from November 5 at 16:00 until November 6 at 11:00.')]
    candidates = [
        row('today', 'New warning', 'A fog warning covers Dolnośląskie from November 6 at 18:00 until November 7 at 10:00.'),
        row('repeat', 'Another outlet', 'IMGW issued a fog alert for Lower Silesia from 6 November at 18:00 until 7 November at 10:00.'),
        row('no-times', 'Short report', 'A fog warning covers Lower Silesia from November 6 until November 7.'),
        history[0],
    ]
    client = client_responses(json.dumps({'decisions': [
        {'index': 0, 'keep': False, 'reason': 'Same topic as yesterday'},
        {'index': 1, 'keep': True, 'reason': 'Different publisher'},
        {'index': 2, 'keep': True, 'reason': 'Shorter version from another outlet'},
        {'index': 3, 'keep': True, 'reason': 'Repeated warning'},
    ]}))
    assert digest._filter_covered_events(client, candidates, history) == candidates[:1]


@pytest.mark.parametrize('response', ['bad JSON', '{"decisions":[]}',
    '{"decisions":[{"index":0,"keep":"false","reason":"repeat"}]}'])
def test_failed_novelty_audit_does_not_consume_queue_or_send(response, monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE bot_kv(k TEXT PRIMARY KEY,v TEXT)')
    digest.init_digest_db(conn)
    current = row('new', 'New policy', 'Residents can apply for new disability support.')
    conn.execute('INSERT INTO digest_articles(id,title,summary_en,url,source,article_date,sort_epoch) VALUES(?,?,?,?,?,?,?)', current)
    conn.commit()
    monkeypatch.setattr(digest, '_recent_digest_history', lambda _c: [row('old', 'Other news', 'An earlier report.')])
    monkeypatch.setattr(digest, '_select_rows', lambda *_a, **_k: [current])
    post = MagicMock()
    monkeypatch.setattr(digest, 'send_to_telegram', post)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        digest.maybe_send_daily_digest(conn, client_responses(response), MagicMock(), (1, 2), 'channel', False, True, 0, 10)
    assert conn.execute('SELECT status FROM digest_articles').fetchone()[0] == 'pending'
    assert conn.execute('SELECT count(*) FROM bot_kv').fetchone()[0] == 0
    post.assert_not_called()
    conn.close()


@pytest.mark.parametrize('host,html,keep', [
    ('radiowroclaw.pl', '<main><div class="articleTeaser">AOW repairs have finished.</div>'
     '<div class="articleContent"><p>The lane opens at 20:00 after the surface hardens.</p>'
     '<div class="jqplayer">Install Flash to listen</div></div>'
     '<div id="mainArticleCommentContainer">Unrelated politician claim</div>'
     '<aside>Recommended other disaster</aside></main>', 'surface hardens'),
    ('jelonka.com', '<article><p class="news-detail__lead">The council passed intent resolutions.</p>'
     '<section id="news-article-body"><p>This starts the procedure, rather than completing it.</p></section>'
     '<section class="news-related-materials">Recommended other disaster</section>'
     '<article class="news-comment">Unrelated politician claim</article></article>', 'starts the procedure'),
    ('swidnica24.pl', '<article><div class="td-post-content"><p>Residents may apply for senior assistance.</p>'
     '<div class="related-posts">Recommended other disaster</div></div>'
     '<section class="comments">Unrelated politician claim</section></article>', 'senior assistance'),
])
def test_publisher_body_keeps_reporting_and_excludes_comments_recommendations(host, html, keep):
    body = _publisher_article_body(html, host)
    assert keep in body
    assert 'Unrelated politician' not in body
    assert 'Recommended other disaster' not in body
    assert 'Install Flash' not in body


def test_radio_fetch_uses_article_body_instead_of_wroclaw_main():
    response = requests.Response()
    response.status_code = 200
    response.url = 'https://www.radiowroclaw.pl/articles/view/165421'
    response._content = ('<main><div class="articleContent"><p>' +
        'The motorway lane will open after the surface hardens. '*8 +
        '</p></div><p>Unrelated reader comment accusing a politician.</p></main>').encode()
    session = MagicMock()
    session.get.return_value = response
    body, error = fetch_article_body(session, response.url, (1, 2))
    assert error is None
    assert 'surface hardens' in body
    assert 'reader comment' not in body


def test_long_summary_gets_one_shortening_pass_and_later_source_qualification(monkeypatch):
    body = 'Earlier background. '*140 + 'The resolutions only begin the procedure; final approval is still required.'
    monkeypatch.setattr('summarize.fetch_article_body', lambda *_a: (body, None))
    long = ' '.join(['word']*80)
    short = 'Piechowice council has started the school merger procedure; final approval is still required.'
    client = client_responses('GO', long, short)
    article = {'title': 'Piechowice schools', 'summary': '', 'link': 'https://example.com/schools'}
    result, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert result == short and reason is None
    assert client.chat.completions.create.call_count == 3
    assert 'final approval is still required' in client.chat.completions.create.call_args_list[1].kwargs['messages'][1]['content']


def test_shortening_remains_bounded_when_model_ignores_limit(monkeypatch):
    monkeypatch.setattr('summarize.fetch_article_body', lambda *_a: ('Reported local facts. '*20, None))
    long = ' '.join(['word']*80)
    client = client_responses('GO', long, long)
    article = {'title': 'Local service', 'summary': '', 'link': 'https://example.com/service'}
    result, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert result is None and reason.startswith('summary too long after shortening')
    assert client.chat.completions.create.call_count == 3


@pytest.mark.parametrize('repair,accepted', [
    ('Piechowice council has started the procedure for a proposed school merger from September 2027.', True),
    ('Piechowice council approved the school merger, effective September 2027.', False),
])
def test_intent_resolution_cannot_become_final_approval(monkeypatch, repair, accepted):
    source = 'Rada przyjęła uchwały intencyjne dotyczące połączenia szkół. Uchwały rozpoczynają procedurę zmian.'
    monkeypatch.setattr('summarize.fetch_article_body', lambda *_a: (source, None))
    client = client_responses('GO', 'Piechowice council approved the school merger, effective September 2027.', repair)
    article = {'title': 'Piechowice schools', 'summary': '', 'link': 'https://example.com/schools'}
    result, reason = summarize_in_english(client, MagicMock(), (1, 2), article)
    assert (result == repair and reason is None) if accepted else (result is None and 'status not preserved' in reason)
    assert client.chat.completions.create.call_count == 3
