import re
import operator
import logging

import rethinkdb as r

from rabix.common.errors import ResourceUnavailable

log = logging.getLogger(__name__)


class RethinkStore(object):
    def __init__(self, db_name='rabix_registry'):
        self.db_name = db_name
        self.cn = r.connect(
            host='localhost',
            port=28015,
            db=db_name,
        )
        self.db = r.db(db_name)
        self.apps = self.db.table('apps')
        self.users = self.db.table('users')

    def disconnect(self):
        self.cn.close()

    def init_db(self):
        r.db_create(self.db_name).run(self.cn)
        r.db(self.db_name).table_create('apps').run(self.cn)
        r.db(self.db_name).table_create('users', primary_key='username') \
            .run(self.cn)

    def _check_error(self, query_result):
        if query_result['errors']:
            raise RuntimeError(
                'Query failed: %s' % query_result['first_error']
            )

    def _build_text_query(self, terms, fields):
        terms = ['(?i)' + re.escape(term) for term in terms]
        q = r.expr(False)
        for field in fields:
            l = [r.row[field].match(term) for term in terms]
            q |= l[0] if len(l) == 1 else reduce(operator.and_, l)
        return q

    def get_user(self, username):
        return self.users.get(username).run(self.cn)

    def get_user_by_token(self, token):
        res = list(self.users.filter({'token': token}).run(self.cn))
        return res[0] if res else None

    def upsert_user(self, user):
        res = self.users.insert(user, upsert=True).run(self.cn)
        self._check_error(res)

    def insert_app(self, *documents):
        map(operator.methodcaller('pop', 'id', ''), documents)
        result = self.apps.insert(*documents).run(self.cn)
        log.debug('Insert result: %s', result)
        self._check_error(result)
        for app, key in zip(documents, result['generated_keys']):
            app['id'] = key

    def update_app(self, document):
        del document['app']
        del document['app_checksum']
        filter = {'repo': document['repo']}
        result = self.apps.get_all(document['id']). \
            filter(filter).update(document).run(self.cn)
        self._check_error(result)
        if not result['updated']:
            raise ResourceUnavailable(document['id'], 'Not found.')
        return self.get_app(document['id'])

    def get_app(self, app_id):
        return self.apps.get(app_id).run(self.cn)

    def filter_apps(self, filter, skip=0, limit=25):
        log.debug('Filter apps: %s', filter)
        cur = self.apps.without('app').filter(filter) \
            .skip(skip).limit(limit).run(self.cn)
        return list(cur)

    def search_apps(self, terms, skip=0, limit=25):
        if not terms:
            return []
        q = self._build_text_query(terms, ('name', 'description'))
        cur = self.apps.without('app').filter(q)\
            .skip(skip).limit(limit).run(self.cn)
        return list(cur)
