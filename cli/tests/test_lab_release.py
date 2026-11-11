"""Candidate lab proof cannot silently accept old, partial or substituted runs."""
import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from devsecops_cli import VERSION, lab_release
from devsecops_cli.lab import source_digest
from devsecops_cli.release_evidence import unpack_evidence

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT, REGION, PROJECT = '123456789012', 'eu-north-1', 'kit-lab-diploma-abcdef'
PREFIX = f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{PROJECT}-dev-lambda-repo@sha256:'
IMAGES = {key:PREFIX+key*64 for key in 'abc'}
ARN = f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PROJECT}-dev-lambda'


class LabReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        fingerprint = source_digest(ROOT)
        wheel = f'devsecops_pipeline_cli-{VERSION}-py3-none-any.whl'
        self.write('artifacts/'+wheel,b'reviewed candidate wheel')
        checksum = hashlib.sha256(b'reviewed candidate wheel').hexdigest()
        self.proof = {'schema_version':2,'scope':'single-operator-dev','production_acceptance':False,
            'version':VERSION,'commit_sha':self.commit,'source_sha256':fingerprint,'repository':'owner/repo',
            'ci_run_id':1,'wheel_sha256':checksum,'account_id':ACCOUNT,'region':REGION,'project_name':PROJECT,
            'api_id':'abcdef','images':IMAGES}
        self.write('release-proof.json',self.proof)
        self.write('release-install.txt',f'devsecops {VERSION}')
        self.write('release-checksums.txt',f'{checksum}  {wheel}\n{wheel}: OK')
        self.write('notes.md','Fixture. Not real AWS proof.')
        self.write('platform-macos.txt','Fixture platform; checked separately by criteria.')
        self.write('platform-debian.txt','Fixture platform; checked separately by criteria.')
        operations=[]
        for number,stage in enumerate(['a','b','c','rollback','destroy'],1):
            event='events/'+stage; plan='plans/'+stage
            op={'operation':'apply','cli_version':VERSION,'source_commit':self.commit,'source_clean':True,
                'source_sha256':fingerprint,'production_acceptance':False,'started_at':f'2026-11-11T10:0{number}:00Z',
                'settings':{'account_id':ACCOUNT,'region':REGION,'project_name':PROJECT}}
            active=IMAGES['b'] if stage=='c' else IMAGES['a' if stage in {'a','rollback','destroy'} else 'b']
            healthy={'function':{'arn':ARN,'image_uri':active},'health':{'status':200,'url':f'https://abcdef.execute-api.{REGION}.amazonaws.com/health'},'state_sha256':'d'*64}
            result={'kind':'single-operator-lab','production_acceptance':False,'account_id':ACCOUNT,'region':REGION,
                    'status':'healthy',**healthy}
            if stage=='c': result.update(status='failed',recovery={'status':'recovered',**healthy})
            if stage=='destroy': result['status']='destroyed'
            self.write(event+'/operation.json',op); self.write(event+'/result.json',result)
            self.write(event+'/command-001.json',{'argv':['terraform','-chdir=terraform/lab','apply','/reviewed/plan.tfplan'],'returncode':0})
            if stage=='c': self.write(event+'/http-001.json',{'status':503})
            self.write(plan+'/plan.tfplan',b'saved binary plan')
            review={'account_id':ACCOUNT,'region':REGION,'source_sha256':fingerprint,
                'stage':'destroy' if stage=='destroy' else 'rollback' if stage=='rollback' else 'workload',
                'image_uri':IMAGES['a' if stage in {'a','rollback','destroy'} else stage],
                'previous':None if stage=='a' else {'image_uri':IMAGES['a' if stage=='b' else 'b']},
                'files':{'plan.tfplan':hashlib.sha256(b'saved binary plan').hexdigest()}}
            self.write(plan+'/review.json',review)
            operations.append({'stage':stage,'event':event,'review':plan+'/review.json','exit_code':1 if stage=='c' else 0})
        self.write('lab-scenario.json',{'operations':operations})
        resources=[]; checks=[]
        identifiers = [
            ('lambda',f'function:{PROJECT}-dev-lambda'),('apigateway','/apis/abcdef'),
            ('apigateway','/apis/abcdef/stages/$default'),('logs',f'log-group:/aws/lambda/{PROJECT}'),
            ('logs',f'log-group:/aws/apigateway/{PROJECT}'),('s3',PROJECT+'-data'),('s3',PROJECT+'-logs'),
            ('ecr','repository/'+PROJECT),('sqs',PROJECT+'-dlq'),('kms','key/fixture-key'),
            ('kms','alias/'+PROJECT),('iam','role/'+PROJECT)]
        for number,(service,identifier) in enumerate(identifiers):
            arn=f'arn:aws:{service}:{REGION}:{ACCOUNT}:{identifier}'
            path=f'cleanup/{number}.json'; target=identifier
            self.write(path,{'argv':['aws',service,'get-resource','--id',target],'returncode':254,'stderr':'ResourceNotFoundException','stdout':''})
            resources.append({'arn':arn});checks.append({'arn':arn,'status':'absent','query_id':target,'evidence':path})
        self.write('inventory.json',{'resources':resources});self.write('state.json',{'resources':[]})
        self.write('cleanup.json',{'account_id':ACCOUNT,'region':REGION,'project_name':PROJECT,
            'managed_resources_after':0,'backup_restore_verified':True,'backend':'local-retained',
            'final_state':'state.json','inventory':'inventory.json','billing_followup':'pending','checks':checks})
        self.manifest()

    def write(self,name,value):
        path=self.directory/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else (json.dumps(value) if isinstance(value,dict) else value).encode())

    def read(self,name): return json.loads((self.directory/name).read_text())

    def manifest(self):
        self.write('manifest.json',{'schema_version':1,'files':{str(p.relative_to(self.directory)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.directory.rglob('*') if p.is_file() and p.name!='manifest.json'}})

    def accepted(self): return lab_release.lab_evidence_checks(ROOT,self.directory)[0]['status']=='OK'

    def test_complete_lab_proof_passes_without_production_reviewer(self):
        self.assertTrue(self.accepted(),lab_release.lab_evidence_checks(ROOT,self.directory))

    def test_wrong_commit_source_wheel_or_production_scope_fails(self):
        for key,value in [('commit_sha','f'*40),('source_sha256','f'*64),('wheel_sha256','f'*64),('production_acceptance',True),('scope','production')]:
            with self.subTest(key=key):
                self.write('release-proof.json',self.proof|{key:value});self.manifest();self.assertFalse(self.accepted())
        self.write('release-proof.json',self.proof)

    def test_rehashed_partial_or_failed_recovery_is_rejected(self):
        path='events/c/result.json';original=self.read(path)
        for result in [original|{'status':'healthy'},original|{'recovery':{'status':'recovery-failed'}},original|{'account_id':'999999999999'}]:
            self.write(path,result);self.manifest();self.assertFalse(self.accepted())

    def test_access_denied_is_not_resource_absence(self):
        value=self.read('cleanup/0.json');value['stderr']='AccessDeniedException'
        self.write('cleanup/0.json',value);self.manifest();self.assertFalse(self.accepted())

    def test_plan_or_raw_record_tamper_fails(self):
        self.write('plans/b/plan.tfplan',b'substituted plan');self.manifest();self.assertFalse(self.accepted())
        self.write('events/a/result.json',{'status':'healthy'});self.assertFalse(self.accepted())

    def test_symlink_and_traversal_paths_are_rejected(self):
        (self.directory/'alias').symlink_to(self.directory/'notes.md')
        for name in ['alias','../notes.md','/etc/passwd']:
            with self.subTest(name=name),self.assertRaises(ValueError):lab_release.checked_path(self.directory,name)

    def test_bundle_roundtrip_checks_every_nested_file(self):
        archive=self.directory.parent/(self.directory.name+'.zip');self.addCleanup(lambda:archive.unlink(missing_ok=True))
        with zipfile.ZipFile(archive,'w') as z:
            for path in self.directory.rglob('*'):
                if path.is_file():z.write(path,str(path.relative_to(self.directory)))
        out=self.directory/'unpacked';unpack_evidence(archive,out)
        self.assertEqual(lab_release.verify_manifest(out),lab_release.verify_manifest(self.directory))

    def test_missing_lifecycle_stage_is_rejected_even_with_fresh_checksums(self):
        scenario=self.read('lab-scenario.json');scenario['operations'].pop(2)
        self.write('lab-scenario.json',scenario);self.manifest();self.assertFalse(self.accepted())
