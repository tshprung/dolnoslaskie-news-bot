"""Read-only source/candidate report. Run with the bot's environment loaded."""
import argparse
import json
import os
import sqlite3
import time


def report(db_path,days=7):
    conn=sqlite3.connect(f'file:{db_path}?mode=ro',uri=True)
    cutoff=int(time.time())-days*86400
    result={
        'candidate_outcomes':conn.execute('SELECT source,stage,reason,count(*) FROM candidate_events WHERE created_at>=? GROUP BY 1,2,3',(cutoff,)).fetchall(),
        'queue':conn.execute('SELECT source,status,count(*) FROM digest_articles GROUP BY 1,2').fetchall(),
        'latest_source_checks':[(source,checked,json.loads(details)) for source,checked,details in conn.execute(
            'SELECT s.source,s.checked_at,s.details FROM source_checks s WHERE s.rowid=(SELECT max(t.rowid) FROM source_checks t WHERE t.source=s.source)')],
    }
    conn.close()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default=os.environ.get('DB_PATH','/opt/dolnoslaskie_news/seen.db'))
    parser.add_argument('--days',type=int,default=7)
    args=parser.parse_args()
    print(json.dumps(report(args.db,max(1,args.days)),ensure_ascii=False,indent=2))
