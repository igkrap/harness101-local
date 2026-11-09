import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
import test_candidate_repair as fixtures


class SeedIntentTests(unittest.TestCase):
    def test_existing_pure_seed_requests_keep_specialized_mode(self):
        from seed_intent import is_seed_task
        for task in ('재고가 음식재료인데 제조업체 예시로','재고 예시를 제조업 자재로','Change inventory seed rows to manufacturing examples','샘플 재고 데이터를 추가해줘'):
            self.assertTrue(is_seed_task(task),task)

    def test_paths_preservation_and_code_identifiers_are_not_seed_edit_intent(self):
        from seed_intent import is_seed_task
        for task in (
            'backend/src/main/java/com/example/localinventory/InventoryController.java에 PUT /api/inventory/{id}를 추가한다. 기존 seed 데이터를 보존한다.',
            'backend/src/main/java/com/example/localinventory/InventoryController.java 수정',
            '탭 닫기 버튼을 아이콘으로 바꿔줘',
            'Preserve existing seed data and implement inventory update API',
            '기존 샘플 데이터를 유지하고 재고 API를 수정한다',
            'sampleCounter inventory 값을 출력한다',
        ):
            self.assertFalse(is_seed_task(task),task)

    def test_actual_failed_backend_goal_is_not_seed_only(self):
        from seed_updates import is_seed_request
        task='재고 화면의 기존 행 수정에 필요한 백엔드 API를 구현한다. backend/src/main/java/com/example/localinventory/InventoryController.java에 PUT /api/inventory/{id}를 추가한다. 기존 InventoryRequest 검증 DTO와 InventoryRepository, 엔티티를 재사용하고 기존 GET 목록/단건, POST 등록 및 seed 데이터를 보존한다. 정상 요청은 기존 행의 이름, 카테고리, 수량, 최소 수량, 단가를 수정해 200과 변경된 JSON을 반환한다. 존재하지 않는 ID는 404, 비어 있는 이름 및 음수 수량 등 유효하지 않은 입력은 400이다. 기존 InventoryIntegrationTest에 PUT 성공 후 GET 재조회로 값 변경 확인, 404, 400 테스트를 추가한다. 테스트는 기존 트랜잭션 격리를 유지하고 원래 테스트의 검증을 약화하지 않는다. 화면 코드는 이번 작업에서 변경하지 않는다.'
        self.assertFalse(is_seed_request(task))


class SeedIntentToolIntegrationTests(unittest.TestCase):
    setUp=fixtures.CandidateRepairTests.setUp
    tearDown=fixtures.CandidateRepairTests.tearDown

    def test_api_work_retains_real_code_editing_tools_despite_preservation_words(self):
        self.runner.modes=['backend']
        self.runner.args.task='backend/src/main/java/com/example/localinventory/InventoryController.java에 PUT /api/inventory/{id}를 구현하고 기존 seed 데이터를 보존한다.'
        names={t['function']['name']for t in self.runner.tools()}
        self.assertIn('apply_edits',names)
        self.assertIn('insert_text',names)
        self.assertIn('write_file',names)
        self.assertNotIn('update_seed_rows',names)
