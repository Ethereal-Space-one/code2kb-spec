"""Mechanical baseline migration gate; fixture approvals are test-only."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'validation/tests'))
import test_knowledge as fixture
from validation.evidence_snapshot import snapshot

class UpgradeBaselineSpikeTests(unittest.TestCase):
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
                    body = body.replace('ENT-001','ENT-004')
                    body = body.replace('backend:dummy.txt:1',account_anchor)
                    if path.name == '结构化规格.md':
                        body = body.replace('| FACT-001 | 用户可提交查询 | CODE_VERIFIED | frontend:dummy.txt:1 |',
                                            f'| FACT-001 | 仅资料本人可查看自己的资料 | CODE_VERIFIED | {account_anchor} |')
                fixture.write(path,body)
            outline = source / '功能大纲.md'
            body = outline.read_text()
            body = body.replace('example.order.query','sample.order.delivery')
            body = body.replace('| app.sales.order |', '| sample.account.profile | 账号 | 资料查看 | 资料请求 | 知识草稿 |\n| app.sales.order |',1)
            body = body.replace('| ENT-003 |',f'| ENT-004 | 后端入口 | 查看资料 | sample.account.profile | {account_anchor} | 已归类 |\n| ENT-003 |',1)
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

            shutil.copy2(ROOT/'conformance/upgrade-two-module/revision-2/src/main/java/example/OrderRule.java',destination/'OrderRule.java')
            subprocess.run(['git','-C',str(backend),'add','.'],check=True)
            subprocess.run(['git','-C',str(backend),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-q','-m','lower delivery threshold'],check=True)
            new = subprocess.check_output(['git','-C',str(backend),'rev-parse','HEAD'],text=True).strip()
            plan = sample.run_cli('preview-upgrade','--all-modules','--plan','--repository-id','backend','--new-commit',new)
            self.assertEqual(plan.returncode, 0, plan.stderr)
            candidate = json.loads(plan.stdout)
            self.assertEqual(candidate['decision'], 'selected_modules')
            self.assertEqual(candidate['selected_modules'], ['sample.order.delivery'])
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
