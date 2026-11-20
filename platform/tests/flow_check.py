"""Does the business-flow judge see what single screens cannot?

Three throwaway screens of the first project - an order (with a status), a shipment that takes over from it, the take-over
screen between them - and a flow over them. Then the cases the user named:
  1. the flow as it is: registered, runs end to end;
  2. "the order makes its shipment by itself" added while the take-over screen is still there: every screen alone is fine,
     the flow is not (a second way to ship the same quantity) - the judge must say so;
  3. the follow-up taken out again (going back): the flow holds again.
Everything is removed at the end. Run: python3 tests/flow_check.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'harness2'))
sys.path.append(str(ROOT / 'platform'))
import flows                     # noqa: E402
from framework import Framework  # noqa: E402

framework = Framework()
ITEM = {'name': 'itemName', 'label': '품목명', 'type': 'text', 'required': True}
ORDER = {'title': '흐름 점검 주문', 'fields': [{'name': 'orderNo', 'label': '주문 번호', 'type': 'serial', 'prefix': 'FT'}, ITEM,
                                         {'name': 'quantity', 'label': '수량', 'type': 'number', 'required': True}],
         'status': {'initial': 'OPEN', 'values': [{'code': 'OPEN', 'label': '접수'}, {'code': 'OK', 'label': '확정'}],
                    'actions': [{'name': 'confirm', 'label': '확정', 'from': ['OPEN'], 'to': 'OK'}], 'locked': []}}
SHIP = {'title': '흐름 점검 출하', 'fields': [{'name': 'orderId', 'label': '주문', 'type': 'ref', 'ref': {'entity': 'ftest_order', 'label': 'orderNo'}, 'required': True},
                                        dict(ITEM, required=False), {'name': 'quantity', 'label': '수량', 'type': 'number', 'required': True}],
        'limits': [{'field': 'quantity', 'by': ['orderId'], 'entity': 'ftest_order', 'entityField': 'quantity', 'entityBy': ['id'], 'message': '주문 수량을 넘을 수 없습니다.'}]}
TAKE = {'title': '흐름 점검 주문 기준 출하', 'take': {'entity': 'ftest_ship', 'from': 'ftest_order', 'statuses': ['OK'], 'set': {'itemName': 'itemName'}}}
AUTO = [{'on': 'confirm', 'create': {'entity': 'ftest_ship', 'set': {'orderId': 'id', 'itemName': 'itemName', 'quantity': 'quantity'}}}]
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('  통과  ' if ok else '  실패  ') + name + ('' if ok else f'\n          {str(detail)[:600]}'))
    return ok


kept = flows.load()
try:
    framework.save_definition('ftest_order', ORDER, 'PUBLISHED')
    framework.save_definition('ftest_ship', SHIP, 'PUBLISHED')
    framework.save_definition('ftest_take', TAKE, 'PUBLISHED')
    done = flows.handle('업무 흐름 등록: 흐름 점검 주문 → 흐름 점검 출하', framework)
    check('흐름 등록: 주문 → (연계) → 출하 가 끝까지 맞게 흐른다', done.get('ok'), '\n'.join(done.get('lines', [])))
    framework.save_definition('ftest_order', dict(ORDER, effects=AUTO), 'PUBLISHED')
    passed, _, said = flows.judge(['ftest_order'], framework)
    check('확정하면 출하가 저절로 생기게 바꾸고 연계 화면도 남겨 두면: 한도가 두 번째 길을 막으므로 흐름은 맞다', passed, said)
    loose = [{'on': 'confirm', 'create': {'entity': 'ftest_ship', 'set': {'itemName': 'itemName', 'quantity': 'quantity', 'orderId': 'id'}}}]
    unlinked = dict(SHIP, fields=[dict(SHIP['fields'][0], required=False)] + SHIP['fields'][1:])
    framework.save_definition('ftest_ship', unlinked, 'PUBLISHED')
    framework.save_definition('ftest_order', dict(ORDER, effects=[{'on': 'confirm', 'create': {'entity': 'ftest_ship', 'set': {'itemName': 'itemName', 'quantity': 'quantity'}}}]), 'PUBLISHED')
    passed, _, said = flows.judge(['ftest_order'], framework)
    check('확정하면 주문을 가리키지 않는 출하가 저절로 생기게 바꾸면: 화면 하나씩은 맞아도 흐름은 같은 수량을 두 번 출하한다고 한다', not passed and any('흐름 밖에서' in line for line in said), said)
    print('          판정: ' + ' / '.join(said)[:300])
    framework.save_definition('ftest_ship', SHIP, 'PUBLISHED')
    framework.save_definition('ftest_order', dict(ORDER, effects=AUTO), 'PUBLISHED')
    framework.call('DELETE', '/api/system/definitions/ftest_take?force=true')
    passed, _, said = flows.judge(['ftest_order'], framework)
    check('연계 화면을 없애 자동 처리 한 길만 남기면: 흐름이 다시 맞다', passed, said)
    framework.save_definition('ftest_take', TAKE, 'PUBLISHED')
    framework.save_definition('ftest_order', ORDER, 'PUBLISHED')
    passed, _, said = flows.judge(['ftest_order'], framework)
    check('되돌려서 연계 한 길로 돌아가면: 흐름이 맞다', passed, said)
    framework.call('DELETE', '/api/system/definitions/ftest_take?force=true')
    passed, _, said = flows.judge(['ftest_order'], framework)
    check('자동 처리도 연계도 없으면: 흐름이 끊긴다고 한다', not passed and any('끊깁니다' in line for line in said), said)
finally:
    flows.save(kept)
    for key in ('ftest_take', 'ftest_ship', 'ftest_order'):
        framework.call('DELETE', f'/api/system/definitions/{key}?force=true')
print(f"\n{sum(results)}/{len(results)} 통과")
sys.exit(0 if all(results) else 1)
