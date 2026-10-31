"""Mechanical baseline migration gate; fixture approvals are test-only."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'validation/tests'))
import test_knowledge as fixture
from validation.evidence_snapshot import snapshot
from validation.upgrade_plan import _git_baseline, _migration_scope, _scope_metrics

class UpgradeBaselineSpikeTests(unittest.TestCase):
    def test_read_only_baseline_does_not_refresh_git_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            fixture.init_fixture_repo(project)
            tracked = project / 'tracked.txt'
            tracked.write_text('unchanged\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(project), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(project), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'base'], check=True)
            index = project / '.git/index'
            original = index.read_bytes()
            stat = tracked.stat()
            os.utime(tracked, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
            head, dirty = _git_baseline(project)
            self.assertEqual(head, subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'],
                                                            text=True).strip())
            self.assertFalse(dirty)
            self.assertEqual(index.read_bytes(), original)

    def test_other_repository_module_is_not_counted_as_migration_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source = project / '知识源'
            docs = []
            relations = {}
            for module_id, repository_id in (('sample.order', 'backend'), ('sample.profile', 'frontend')):
                folder = source / module_id
                folder.mkdir(parents=True)
                (folder / '关系映射.json').write_text('{}', encoding='utf-8')
                for name, doc_type in (('结构化规格.md', 'spec'), ('功能与范围.md', 'scope'),
                                       ('发布清单.md', 'release_manifest')):
                    docs.append(SimpleNamespace(module_id=module_id, doc_type=doc_type,
                                                relative=Path(module_id) / name,
                                                meta={'source_revisions': f'{repository_id}=fixed',
                                                      'review_status': 'reviewed'}))
                relations[module_id] = {'data': {'nodes': []}, 'links': [
                    {'evidence': [{'repository_id': repository_id, 'path': 'source.java'}]}]}
            preview = {'repository_id': 'backend', 'changed_files': [{'path': 'source.java'}],
                       'possible_modules': ['sample.order']}
            scope = _migration_scope(project, source, preview, docs, relations,
                                     ['sample.order', 'sample.profile'], False, [])
            by_id = {item['module_id']: item for item in scope['modules']}
            self.assertTrue(by_id['sample.order']['review_reset_files'])
            self.assertEqual(by_id['sample.profile']['source_revision_files'], [])
            self.assertEqual(by_id['sample.profile']['review_reset_files'], [])
            self.assertEqual(by_id['sample.profile']['manifest_files'], [])
            self.assertIsNone(by_id['sample.profile']['relation_file'])
            self.assertEqual(_scope_metrics(scope)['baseline_touch_modules'], 1)
            self.assertEqual(_scope_metrics(scope)['approval_refresh_modules'], 1)

    def test_two_module_baseline_migration_requires_reapproval(self) -> None:
        sample = fixture.KnowledgeTests('test_publish_isolated_views_and_no_overwrite')
        sample.setUp()
        try:
            project = sample.project
            source = sample.source
            backend = Path(sample.repos['backend']['path'])
            base_files = ROOT / 'conformance/upgrade-two-module/base/src/main/java/example'
            destination = backend / 'src/main/java/example'
            destination.mkdir(parents=True)
            for name in ('OrderRule.java', 'AccountRule.java'):
                shutil.copy2(base_files / name, destination / name)
            subprocess.run(['git','-C',str(backend),'add','.'],check=True)
            subprocess.run(['git','-C',str(backend),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-q','-m','two module base'],check=True)
            base = subprocess.check_output(['git','-C',str(backend),'rev-parse','HEAD'],text=True).strip()
            old = sample.repos['backend']['commit']
            config_path = project / '知识库配置.json'
            config = json.loads(config_path.read_text())
            config['repositories']['backend']['commit'] = base
            config.pop('inventory_adapter')
            fixture.write(config_path,json.dumps(config,ensure_ascii=False))
            sample.repos['backend']['commit'] = base

            account = source / '账号/资料查看'
            shutil.copytree(sample.module, account)
            (account/'发布清单.md').unlink(missing_ok=True)
            (sample.module/'发布清单.md').unlink(missing_ok=True)
            order_anchor = 'backend:src/main/java/example/OrderRule.java:5'
            account_anchor = 'backend:src/main/java/example/AccountRule.java:5'
            for path in source.rglob('*.md'):
                body = path.read_text()
                body = body.replace(old,base)
                if path.parent == sample.module:
                    body = body.replace('example.order.query','sample.order.delivery')
                    body = body.replace('backend:dummy.txt:1',order_anchor)
                    if path.name == '结构化规格.md':
                        body = body.replace('| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 |',
                                            f'| FACT-001 | 满100个货币单位免配送费，否则收5个单位 | CODE_VERIFIED | {order_anchor} |')
                if path.parent == account:
                    body = body.replace('example.order.query','sample.account.profile').replace('订单查询','资料查看')
                    if path.name == '结构化规格.md':
                        body = body.split('## 大纲覆盖核对\n', 1)[0]
                    body = body.replace('ENT-001','ENT-004')
                    body = body.replace('backend:dummy.txt:1',account_anchor)
                    if path.name == '结构化规格.md':
                        body = body.replace('| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 |',
                                            f'| FACT-001 | 仅资料本人可查看自己的资料 | CODE_VERIFIED | {account_anchor} |')
                fixture.write(path,body)
            outline = source / '功能大纲.md'
            body = outline.read_text()
            body = body.replace('example.order.query','sample.order.delivery')
            body = body.replace('| app.sales.order | 销售 | 订单 | 菜单入口 | 待提取 |',
                                '| sample.account.profile | 账号 | 资料查看 | 资料请求 | 知识草稿 |', 1)
            body = '\n'.join(f'| ENT-004 | 后端入口 | 查看资料 | sample.account.profile | {account_anchor} | 已归类 |'
                             if line.startswith('| ENT-003 |') else line for line in body.split('\n'))
            fixture.write(outline,body)

            for module, module_id, anchor in ((sample.module,'sample.order.delivery',order_anchor),(account,'sample.account.profile',account_anchor)):
                record = snapshot(anchor,config['repositories'])
                relation = {'schema_version':'0.1','module_id':module_id,'nodes':[],'identity_history':[],
                            'topics':[{'topic_id':'topic.answer','audience':'business','source_document':'功能与范围.md','source_heading':'说明'}],
                            'links':[{'from_type':'fact','from_id':'FACT-001','to_type':'topic','to_id':'topic.answer','status':'verified',
                                      'evidence':[record],'reviewed_by':'Fixture reviewer','reviewed_at':'2026-10-26'}]}
                fixture.write(module/'关系映射.json',json.dumps(relation,ensure_ascii=False))

            for module_id in ('sample.order.delivery','sample.account.profile'):
                fixture.finalize_fixture(project,module_id)
            checked = sample.run_cli('check')
            self.assertEqual(checked.returncode, 0, checked.stderr)
            published = sample.run_cli('publish','--release-id','two-module-base')
            self.assertEqual(published.returncode, 0, published.stderr)
            subprocess.run(['git','-C',str(project),'add','.'],check=True)
            subprocess.run(['git','-C',str(project),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-q','-m','base release'],check=True)
            project_index = project / '.git/index'
            index_before_preview = project_index.read_bytes()
            config_path = project / '知识库配置.json'
            config_stat = config_path.stat()
            os.utime(config_path, ns=(config_stat.st_atime_ns, config_stat.st_mtime_ns + 10_000_000_000))

            shutil.copy2(ROOT/'conformance/upgrade-two-module/revision-2/src/main/java/example/OrderRule.java',destination/'OrderRule.java')
            subprocess.run(['git','-C',str(backend),'add','.'],check=True)
            subprocess.run(['git','-C',str(backend),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-q','-m','lower delivery threshold'],check=True)
            new = subprocess.check_output(['git','-C',str(backend),'rev-parse','HEAD'],text=True).strip()
            plan = sample.run_cli('preview-upgrade','--all-modules','--plan','--repository-id','backend','--new-commit',new)
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertEqual(project_index.read_bytes(), index_before_preview)
            candidate = json.loads(plan.stdout)
            self.assertEqual(candidate['decision'], 'selected_modules')
            self.assertEqual(candidate['selected_modules'], ['sample.order.delivery'])
            self.assertEqual(candidate['review_scope_metrics']['modules_total'], 2)
            self.assertEqual(candidate['review_scope_metrics']['semantic_review_modules'], 1)
            self.assertEqual(candidate['review_scope_metrics']['baseline_touch_modules'], 2)
            self.assertEqual(candidate['review_scope_metrics']['approval_refresh_modules'], 2)
            evidence_path = project / '运行证据/订单/订单查询/测试观测.md'
            fixture.write(evidence_path,
                          '---\ndocument_type: runtime_evidence\nevidence_id: EVID-001\n'
                          'module_id: sample.order.delivery\nevidence_type: runtime\nenvironment: 测试\n'
                          'observed_at: 2026-10-25\nvalid_until: 2099-01-01\nfact_ids: FACT-001\n'
                          f'source_revisions: "backend={base}"\n---\n\n# 测试观测\n\n'
                          '## 来源与方法\n\n公开夹具中的测试日志。\n\n'
                          '## 观察或确认结果\n\n仅记录旧提交下的结果。\n\n'
                          '## 适用范围与不能证明的事项\n\n不能证明新提交的运行表现。\n\n'
                          '## 脱敏说明\n\n无个人资料。\n')
            subprocess.run(['git', '-C', str(project), 'add', '运行证据'], check=True)
            subprocess.run(['git', '-C', str(project), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'old runtime observation'],
                           check=True)
            runtime_plan = sample.run_cli('preview-upgrade', '--all-modules', '--plan',
                                          '--repository-id', 'backend', '--new-commit', new)
            self.assertEqual(runtime_plan.returncode, 0, runtime_plan.stderr)
            runtime_candidate = json.loads(runtime_plan.stdout)
            self.assertEqual(runtime_candidate['decision'], 'full_project_review')
            self.assertIn('source_bound_runtime_evidence_requires_review', runtime_candidate['fallback_reasons'])
            self.assertEqual(runtime_candidate['review_scope_metrics']['runtime_evidence_requiring_review'], 1)
            self.assertEqual(runtime_candidate['baseline_migration']['runtime_evidence_requiring_independent_review'][0]['path'],
                             '运行证据/订单/订单查询/测试观测.md')
            evidence_path.unlink()
            subprocess.run(['git', '-C', str(project), 'add', '-u'], check=True)
            subprocess.run(['git', '-C', str(project), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'remove observation'],
                           check=True)
            migration = {row['module_id']: row for row in candidate['baseline_migration']['modules']}
            self.assertEqual(set(migration), {'sample.order.delivery', 'sample.account.profile'})
            self.assertFalse(migration['sample.account.profile']['semantic_review_required'])
            self.assertTrue(migration['sample.account.profile']['source_revision_files'])
            self.assertEqual(migration['sample.account.profile']['evidence_records_rebuildable'], 1)
            self.assertEqual(migration['sample.account.profile']['evidence_records_requiring_review'], 0)
            self.assertTrue(migration['sample.account.profile']['review_reset_files'])
            self.assertEqual(len(migration['sample.account.profile']['manifest_files']), 1)
            account_business = (account/'功能与范围.md').read_bytes()
            original_account_record = json.loads((account/'关系映射.json').read_text())['links'][0]['evidence'][0]

            config['repositories']['backend']['commit'] = new
            fixture.write(config_path,json.dumps(config,ensure_ascii=False))
            for path in source.rglob('*.md'):
                body=path.read_text().replace(base,new)
                if path.parent == sample.module:
                    body=body.replace('满100个货币单位免配送费，否则收5个单位','满80个货币单位免配送费，否则收5个单位')
                fixture.write(path,body)
            for module,anchor in ((sample.module,order_anchor),(account,account_anchor)):
                relation_path=module/'关系映射.json'
                relation=json.loads(relation_path.read_text())
                relation['links'][0]['evidence']=[snapshot(anchor,config['repositories'])]
                fixture.write(relation_path,json.dumps(relation,ensure_ascii=False))
            self.assertEqual((account/'功能与范围.md').read_bytes(), account_business)
            updated_account_record = json.loads((account/'关系映射.json').read_text())['links'][0]['evidence'][0]
            self.assertEqual(updated_account_record['snippet_sha256'], original_account_record['snippet_sha256'])
            self.assertEqual(updated_account_record['blob_oid'], original_account_record['blob_oid'])
            self.assertNotEqual(updated_account_record['commit'], original_account_record['commit'])
            stale = sample.run_cli('check')
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('发布清单', stale.stderr)
            for module in (sample.module,account):
                (module/'发布清单.md').unlink(missing_ok=True)
            for module_id in ('sample.order.delivery','sample.account.profile'):
                fixture.finalize_fixture(project,module_id)
            checked=sample.run_cli('check')
            self.assertEqual(checked.returncode, 0, checked.stderr)
            audited=sample.run_cli('audit-release','--release-id','two-module-base')
            self.assertEqual(audited.returncode, 0, audited.stderr)
            published=sample.run_cli('publish','--release-id','two-module-next')
            self.assertEqual(published.returncode, 0, published.stderr)
            self.assertEqual(sample.run_cli('audit-release','--release-id','two-module-next').returncode, 0)
        finally:
            sample.doCleanups()
