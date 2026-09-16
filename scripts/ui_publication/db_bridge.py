"""Runs inside the deployed backend with its existing database configuration."""
import json
import sys

from backend.app.core.postgres_database import postgres_database as db

request = json.load(sys.stdin)
with db.transaction() as conn:
    if request['action'] == 'snapshot':
        sources = conn.execute("SELECT source_id,last_success_at,error FROM ui_discovery_sources WHERE source_id='hyperui'").fetchall()
        candidates = conn.execute("""
            SELECT c.candidate_id,c.revision,c.payload,c.review_status
            FROM ui_discovery_candidates c
            LEFT JOIN ui_discovery_source_configs cfg
              ON cfg.id::text = c.payload->>'discovery_source_config_id'
            WHERE c.review_status IN ('pending','held_quality') AND (
              c.source_id='hyperui' OR (
                c.source_id LIKE 'x:%' AND c.payload->>'kind'='x_github_html'
                AND c.payload->>'auto_publish_eligible'='true'
                AND cfg.enabled AND cfg.x_auto_publish
                AND lower(cfg.repository)=lower(c.payload->>'repo')
              )
            )
            ORDER BY CASE c.review_status WHEN 'pending' THEN 0 ELSE 1 END,
              CASE c.change_kind WHEN 'new' THEN 0 WHEN 'updated' THEN 1 ELSE 2 END,
              c.candidate_id
        """).fetchall()
        print(json.dumps({'sources': sources, 'candidates': candidates}, default=str))
    elif request['action'] == 'record':
        for item in request.get('items', []):
            if item['status'] not in ('published', 'held_policy', 'held_duplicate', 'held_render', 'held_quality'):
                raise ValueError('invalid review status')
            # Never approve a revision discovered after this worker's snapshot.
            conn.execute('UPDATE ui_discovery_candidates SET review_status=%s WHERE candidate_id=%s AND revision=%s', (item['status'], item['candidate_id'], item['revision']))
        conn.execute("INSERT INTO ui_discovery_sources(source_id,revision,checked_at,last_success_at,error) VALUES ('publication',%s,now(),CASE WHEN %s THEN now() ELSE NULL END,%s) ON CONFLICT(source_id) DO UPDATE SET revision=EXCLUDED.revision,checked_at=now(),last_success_at=COALESCE(EXCLUDED.last_success_at,ui_discovery_sources.last_success_at),error=EXCLUDED.error", (request['run_id'], request['success'], request.get('error')))
        print(json.dumps({'recorded': len(request.get('items', []))}))
    else:
        raise ValueError('unknown action')
db.close()
