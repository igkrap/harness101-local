package com.example.localinventory.framework.app;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;

/**
 * Stock by lot, moved by the records of the screens whose definition has a "stock" part.
 *
 * A receiving screen (direction in) makes one lot per line: the item, the warehouse, the quantity and the unit cost of that line.
 * An issuing screen (direction out) takes its quantity from the oldest lots of the item in the warehouse first, and each part taken
 * carries the cost of the lot it came from - so every issue has its cost, lot by lot, for the accounts. More than there is in stock
 * is refused. Changing or deleting a record first takes its movements back (a lot something was already issued from cannot be taken back).
 */
@Service
public class QuantityLedger {
    private final JdbcTemplate jdbc;
    private final AppDefinitions definitions;
    private final RecordStore store;
    private final tools.jackson.databind.ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    private final PeriodLocks locks;
    public QuantityLedger(JdbcTemplate jdbc, AppDefinitions definitions, RecordStore store, PeriodLocks locks) { this.jdbc = jdbc; this.definitions = definitions; this.store = store; this.locks = locks; }

    /** Whether this thing is kept by numbered lots: what the stock screens moving it say (lotWhen: its record's field holds one of the values);
     *  when none of them says, any thing may carry a lot number. Answered LOT or NONE. */
    public String tracking(String thingEntity, long thing) {
        AppDefinitions.LotWhen rule = null;
        for (AppDefinitions.Stored stored : definitions.all()) {
            AppDefinitions.Ledger ledger = stored.definition().ledger();
            if (ledger != null && ledger.lotWhen() != null && thingEntity.equals(ledger.thingEntity())) { rule = ledger.lotWhen(); break; }
        }
        if (rule == null) return "LOT";
        AppDefinitions.Stored stored = definitions.find(thingEntity);
        String data = stored == null ? null : store.data(stored.definition(), thing);
        JsonNode value = data == null ? null : mapper.readTree(data).get(rule.field());
        return value != null && !value.isNull() && rule.is().contains(value.asString()) ? "LOT" : "NONE";
    }
    /** The lot number typed on a line, for an item kept by lot; typed for an item kept by quantity only, it is refused. */
    private String typedLot(AppDefinitions.Definition definition, AppDefinitions.Ledger ledger, JsonNode line, JsonNode data, long thing, String where) {
        JsonNode value = at(line, data, ledger.lot());
        String typed = value == null || value.isNull() ? "" : value.asString().trim();
        if (typed.isEmpty()) return null;
        if (!tracking(ledger.thingEntity(), thing).equals("LOT"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, where + "이 " + label(definition, ledger.thing()) + "은(는) 묶음 번호로 관리하지 않아 " + label(definition, ledger.lot()) + "을(를) 적을 수 없습니다.");
        return typed;
    }

    /** A field of the screen by the words people see on it. */
    private static String label(AppDefinitions.Definition definition, String name) {
        if (name == null) return "";
        AppDefinitions.Field field = definition.field(name);
        if (field == null) for (AppDefinitions.LineSet set : definition.lineSets()) for (AppDefinitions.Field one : set.fields()) if (one.name().equals(name)) field = one;
        return field == null ? name : field.label();
    }
    private static JsonNode at(JsonNode line, JsonNode header, String name) { return name == null ? null : line != null && line.has(name) ? line.get(name) : header.get(name); }
    private static BigDecimal number(JsonNode value) { return value == null || value.isNull() || !value.isNumber() ? null : new BigDecimal(value.asString()); }
    private static String shown(BigDecimal value) { return value.stripTrailingZeros().toPlainString(); }

    /** The last month whose stock is closed (2026-10), or null: every month up to it is closed (months are closed in order). */
    public String closedThrough() {
        // the ledger asks the locks of the groups its own screens belong to; the furthest of them holds the whole ledger (none: not locked)
        String furthest = null;
        for (AppDefinitions.Stored stored : definitions.all()) {
            AppDefinitions.Definition definition = stored.definition();
            if (!stored.status().equals("PUBLISHED") || definition.ledger() == null || definition.lock() == null) continue;
            String through = locks.through(definition.lock().group());
            if (through != null && (furthest == null || through.compareTo(furthest) > 0)) furthest = through;
        }
        return furthest;
    }
    /** A month of a group closed: if the group holds screens that move this ledger, what each lot held at the month's end is kept. */
    @org.springframework.context.event.EventListener
    public void closed(PeriodLocks.Closed closed) {
        boolean ours = definitions.all().stream().anyMatch(stored -> stored.definition().ledger() != null && stored.definition().lock() != null && stored.definition().lock().group().equals(closed.group()));
        if (!ours) return;
        jdbc.update("INSERT INTO ledger_month_end (lock_group, period, thing_id, place_id, lot_id, quantity, amount) "
                + "SELECT ?, ?, thing_id, place_id, lot_id, SUM(CASE WHEN direction = 'IN' THEN quantity ELSE -quantity END), SUM(CASE WHEN direction = 'IN' THEN amount ELSE -amount END) "
                + "FROM ledger_moves WHERE moved_on < ? GROUP BY thing_id, place_id, lot_id "
                + "HAVING SUM(CASE WHEN direction = 'IN' THEN quantity ELSE -quantity END) <> 0 OR SUM(CASE WHEN direction = 'IN' THEN amount ELSE -amount END) <> 0",
                closed.group(), closed.month().toString(), java.sql.Date.valueOf(closed.month().plusMonths(1).atDay(1)));
    }
    @org.springframework.context.event.EventListener
    public void reopened(PeriodLocks.Reopened reopened) {
        jdbc.update("DELETE FROM ledger_month_end WHERE lock_group = ? AND period = ?", reopened.group(), reopened.month().toString());
    }
    private static String month(String period) { return period.substring(0, 4) + "년 " + Integer.parseInt(period.substring(5, 7)) + "월"; }
    /** Nothing moves on a day of a closed month. */
    private void open(java.time.LocalDate day, String what) {
        String through = closedThrough();
        if (through != null && day.toString().substring(0, 7).compareTo(through) <= 0)
            throw new ResponseStatusException(HttpStatus.CONFLICT, month(through) + "까지 마감되어 " + what + " (날짜 " + day.toString().replace('-', '/')
                    + "). 「마감」 화면에서 그 달을 다시 열 수 있습니다.");
    }
    /** Stock of a closed month names its item and warehouse: those records stay (an item or warehouse that only an adjustment or a count moved, too). */
    public void named(String entity, long id) {
        String through = closedThrough();
        if (through == null) return;
        Integer held = jdbc.queryForObject("SELECT COUNT(*) FROM ledger_moves m JOIN ledger_lots l ON l.lot_id = m.lot_id WHERE m.moved_on < ? "
                + "AND ((l.thing_entity = ? AND l.thing_id = ?) OR (l.place_entity = ? AND l.place_id = ?))", Integer.class,
                java.sql.Date.valueOf(java.time.YearMonth.parse(through).plusMonths(1).atDay(1)), entity, id, entity, id);
        if (held != null && held > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, month(through) + "까지 마감되었고 그 안의 수량 기록이 이 자료를 가리키고 있어 지울 수 없습니다.");
    }
    /** A whole screen removed with its records: refused while stock of a closed month was moved by it or names its records (items, warehouses). */
    public void screenOpen(String entity, String title) {
        String through = closedThrough();
        if (through == null) return;
        Integer held = jdbc.queryForObject("SELECT COUNT(*) FROM ledger_moves m JOIN ledger_lots l ON l.lot_id = m.lot_id WHERE m.moved_on < ? "
                + "AND (m.entity_key = ? OR l.thing_entity = ? OR l.place_entity = ?)", Integer.class,
                java.sql.Date.valueOf(java.time.YearMonth.parse(through).plusMonths(1).atDay(1)), entity, entity, entity);
        if (held != null && held > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, month(through) + "까지 마감되었고 " + title + " 의 수량 기록 " + held + "건이 그 안에 있어 화면과 자료를 지울 수 없습니다.");
    }
    /** A record whose stock moved in a closed month stays as it is (no change, deletion or status action). */
    public void open(AppDefinitions.Definition definition, long id, String word) {
        if (definition.ledger() == null) return;
        java.sql.Date first = jdbc.queryForObject("SELECT MIN(moved_on) FROM ledger_moves WHERE entity_key = ? AND record_id = ?", java.sql.Date.class, definition.key(), id);
        if (first != null) open(first.toLocalDate(), definition.title().replaceAll("\\s*(등록|관리|입력)$", "") + " 자료를 " + word + "할 수 없습니다");
    }

    /** Take back what the record moved (before it is changed or deleted): what it took from lots goes back, the lots it made go away -
     *  unless something was already issued or moved on from them. */
    public void reverse(AppDefinitions.Definition definition, long id) {
        if (definition.ledger() == null) return;
        open(definition, id, "수정·삭제");
        Integer used = jdbc.queryForObject("SELECT COUNT(*) FROM ledger_lots WHERE source_entity = ? AND source_id = ? AND remaining_qty <> received_qty", Integer.class, definition.key(), id);
        if (used != null && used > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, "이 자료로 들어온 수량 중 이미 다른 자료에서 꺼내 쓴 것이 있어 고치거나 지울 수 없습니다. 그쪽을 먼저 되돌려야 합니다.");
        jdbc.update("UPDATE ledger_lots l SET remaining_qty = l.remaining_qty + m.quantity FROM (SELECT lot_id, SUM(quantity) AS quantity FROM ledger_moves WHERE entity_key = ? AND record_id = ? AND direction = 'OUT' GROUP BY lot_id) m WHERE l.lot_id = m.lot_id", definition.key(), id);
        jdbc.update("DELETE FROM ledger_moves WHERE entity_key = ? AND record_id = ?", definition.key(), id);
        jdbc.update("DELETE FROM ledger_lots WHERE source_entity = ? AND source_id = ?", definition.key(), id);
    }

    /** Move stock as the record (as it is stored now) says. */
    public void post(AppDefinitions.Definition definition, long id, JsonNode data, String user) {
        AppDefinitions.Ledger ledger = definition.ledger();
        if (ledger == null) return;
        List<JsonNode> units = new ArrayList<>();
        boolean lined = definition.lines() != null && definition.lines().fields().stream().anyMatch(field -> field.name().equals(ledger.quantity()));
        if (lined) for (JsonNode line : data.path("lines")) units.add(line); else units.add(null);
        java.time.LocalDate day = RecordController.today();
        int number = 0;
        for (JsonNode line : units) {
            number++;
            JsonNode thing = at(line, data, ledger.thing()), place = at(line, data, ledger.place()), on = at(line, data, ledger.date());
            BigDecimal quantity = number(at(line, data, ledger.quantity()));
            if (thing == null || thing.isNull() || quantity == null || quantity.signum() < 0 || (quantity.signum() == 0 && !ledger.direction().equals("count"))) continue;
            if (place == null || place.isNull()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, label(definition, ledger.place()) + "이(가) 있어야 합니다.");
            java.sql.Date moved = java.sql.Date.valueOf(on != null && !on.isNull() && on.asString().matches("\\d{4}-\\d{2}-\\d{2}") ? java.time.LocalDate.parse(on.asString()) : day);
            String where = lined ? number + "번째 줄: " : "", lotNo = typedLot(definition, ledger, line, data, thing.asLong(), where);
            open(moved.toLocalDate(), where + "그 날짜로 재고를 움직일 수 없습니다");
            if (ledger.direction().equals("count")) {     // the counted quantity: the books are set to it, the difference goes in or out
                BigDecimal book = jdbc.queryForObject("SELECT COALESCE(SUM(remaining_qty), 0) FROM ledger_lots WHERE thing_id = ? AND place_id = ? AND (CAST(? AS varchar) IS NULL OR lot_no = ?)", BigDecimal.class, thing.asLong(), place.asLong(), lotNo, lotNo);
                BigDecimal difference = quantity.subtract(book), cost = number(at(line, data, ledger.unitCost()));
                if (difference.signum() > 0) {
                    if (cost == null) { List<BigDecimal> last = jdbc.queryForList("SELECT unit_cost FROM ledger_lots WHERE thing_id = ? AND place_id = ? ORDER BY received_on DESC, lot_id DESC LIMIT 1", BigDecimal.class, thing.asLong(), place.asLong()); cost = last.isEmpty() ? BigDecimal.ZERO : last.get(0); }
                    Long lot = jdbc.queryForObject("INSERT INTO ledger_lots (thing_entity, thing_id, place_entity, place_id, unit_cost, received_qty, remaining_qty, received_on, source_entity, source_id, source_line) "
                            + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING lot_id", Long.class, ledger.thingEntity(), thing.asLong(), ledger.placeEntity(), place.asLong(), cost, difference, difference, moved, definition.key(), id, number);
                    jdbc.update("UPDATE ledger_lots SET lot_no = ? WHERE lot_id = ?", lotNo != null ? lotNo : "LOT-" + moved.toLocalDate().format(java.time.format.DateTimeFormatter.ofPattern("yyMMdd")) + "-" + String.format("%05d", lot), lot);
                    jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, ?, ?, 'IN', ?, ?, ?, ?, ?, ?, ?, ?)",
                            definition.key(), id, number, thing.asLong(), place.asLong(), lot, difference, cost, difference.multiply(cost), moved, user);
                } else if (difference.signum() < 0) {
                    BigDecimal left = difference.negate();
                    for (Map<String, Object> lot : jdbc.queryForList("SELECT lot_id, remaining_qty, unit_cost FROM ledger_lots WHERE thing_id = ? AND place_id = ? AND remaining_qty > 0 AND (CAST(? AS varchar) IS NULL OR lot_no = ?) ORDER BY received_on, lot_id FOR UPDATE", thing.asLong(), place.asLong(), lotNo, lotNo)) {
                        if (left.signum() <= 0) break;
                        BigDecimal take = ((BigDecimal) lot.get("remaining_qty")).min(left), unit = (BigDecimal) lot.get("unit_cost");
                        jdbc.update("UPDATE ledger_lots SET remaining_qty = remaining_qty - ? WHERE lot_id = ?", take, lot.get("lot_id"));
                        jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, ?, ?, 'OUT', ?, ?, ?, ?, ?, ?, ?, ?)",
                                definition.key(), id, number, thing.asLong(), place.asLong(), lot.get("lot_id"), take, unit, take.multiply(unit), moved, user);
                        left = left.subtract(take);
                    }
                }
                continue;
            }
            if (ledger.direction().equals("in")) {
                BigDecimal cost = number(at(line, data, ledger.unitCost()));
                if (cost == null) cost = BigDecimal.ZERO;
                Long lot = jdbc.queryForObject("INSERT INTO ledger_lots (thing_entity, thing_id, place_entity, place_id, unit_cost, received_qty, remaining_qty, received_on, source_entity, source_id, source_line) "
                        + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING lot_id", Long.class, ledger.thingEntity(), thing.asLong(), ledger.placeEntity(), place.asLong(), cost, quantity, quantity, moved, definition.key(), id, number);
                jdbc.update("UPDATE ledger_lots SET lot_no = ? WHERE lot_id = ?", lotNo != null ? lotNo : "LOT-" + moved.toLocalDate().format(java.time.format.DateTimeFormatter.ofPattern("yyMMdd")) + "-" + String.format("%05d", lot), lot);
                jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, ?, ?, 'IN', ?, ?, ?, ?, ?, ?, ?, ?)",
                        definition.key(), id, number, thing.asLong(), place.asLong(), lot, quantity, cost, quantity.multiply(cost), moved, user);
            } else {
                boolean moving = ledger.direction().equals("move");
                JsonNode to = moving ? at(line, data, ledger.toPlace()) : null;
                if (moving && (to == null || to.isNull())) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, where + label(definition, ledger.toPlace()) + "이(가) 있어야 합니다.");
                if (moving && to.asLong() == place.asLong()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, where + label(definition, ledger.place()) + "와(과) " + label(definition, ledger.toPlace()) + "이(가) 같습니다.");
                BigDecimal left = quantity;
                // oldest lots first; the rows are held until this request ends, so two issues cannot take the same stock
                // (a lot asked for by its number: only lots of that number are taken from)
                for (Map<String, Object> lot : jdbc.queryForList("SELECT lot_id, lot_no, received_on, remaining_qty, unit_cost FROM ledger_lots WHERE thing_id = ? AND place_id = ? AND remaining_qty > 0 AND (CAST(? AS varchar) IS NULL OR lot_no = ?) "
                        + "AND NOT (source_entity = ? AND source_id = ?) ORDER BY received_on, lot_id FOR UPDATE", thing.asLong(), place.asLong(), lotNo, lotNo, definition.key(), id)) {
                    if (left.signum() <= 0) break;
                    BigDecimal has = (BigDecimal) lot.get("remaining_qty"), take = has.min(left), cost = (BigDecimal) lot.get("unit_cost");
                    jdbc.update("UPDATE ledger_lots SET remaining_qty = remaining_qty - ? WHERE lot_id = ?", take, lot.get("lot_id"));
                    jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, ?, ?, 'OUT', ?, ?, ?, ?, ?, ?, ?, ?)",
                            definition.key(), id, number, thing.asLong(), place.asLong(), lot.get("lot_id"), take, cost, take.multiply(cost), moved, user);
                    if (moving) {       // the same lot, now in the other warehouse: its number, its cost and the day it first came in go with it
                        Long arrived = jdbc.queryForObject("INSERT INTO ledger_lots (lot_no, thing_entity, thing_id, place_entity, place_id, unit_cost, received_qty, remaining_qty, received_on, source_entity, source_id, source_line) "
                                + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING lot_id", Long.class, lot.get("lot_no"), ledger.thingEntity(), thing.asLong(), ledger.placeEntity(), to.asLong(), cost, take, take, lot.get("received_on"), definition.key(), id, number);
                        jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, ?, ?, 'IN', ?, ?, ?, ?, ?, ?, ?, ?)",
                                definition.key(), id, number, thing.asLong(), to.asLong(), arrived, take, cost, take.multiply(cost), moved, user);
                    }
                    left = left.subtract(take);
                }
                if (left.signum() > 0)
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, where + label(definition, ledger.place()) + "의 남은 수량이 모자랍니다 (필요 " + shown(quantity) + ", " + (lotNo == null ? "남은 수량 " : label(definition, ledger.lot()) + " " + lotNo + " 의 남은 수량 ") + shown(quantity.subtract(left)) + ").");
            }
        }
    }

    /**
     * Stock put in or taken out without a record of a screen behind it: the opening stock, the difference a count found.
     * A positive quantity makes a lot at the given cost; a negative one is taken from the oldest lots like any issue.
     */
    public void adjust(String thingEntity, long thing, String placeEntity, long place, BigDecimal quantity, BigDecimal cost, String user) { adjust(thingEntity, thing, placeEntity, place, quantity, cost, user, "_adjust", null); }
    /** source: what the ledger says moved it (_adjust: opening stock, _count: a stock count). lotNo: for an item kept by lot, the lot's own number. */
    public void adjust(String thingEntity, long thing, String placeEntity, long place, BigDecimal quantity, BigDecimal cost, String user, String source, String lotNo) {
        if (lotNo != null && !lotNo.isBlank() && !tracking(thingEntity, thing).equals("LOT"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "묶음 번호로 관리하지 않는 것이라 묶음 번호를 적을 수 없습니다.");
        java.sql.Date day = java.sql.Date.valueOf(RecordController.today());
        open(day.toLocalDate(), "재고를 조정할 수 없습니다");
        if (quantity.signum() > 0) {
            Long lot = jdbc.queryForObject("INSERT INTO ledger_lots (thing_entity, thing_id, place_entity, place_id, unit_cost, received_qty, remaining_qty, received_on, source_entity, source_id, source_line) "
                    + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0) RETURNING lot_id", Long.class, thingEntity, thing, placeEntity, place, cost == null ? BigDecimal.ZERO : cost, quantity, quantity, day, source);
            jdbc.update("UPDATE ledger_lots SET lot_no = ? WHERE lot_id = ?", lotNo != null && !lotNo.isBlank() ? lotNo.trim() : "LOT-" + day.toLocalDate().format(java.time.format.DateTimeFormatter.ofPattern("yyMMdd")) + "-" + String.format("%05d", lot), lot);
            jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, 0, 0, 'IN', ?, ?, ?, ?, ?, ?, ?, ?)",
                    source, thing, place, lot, quantity, cost == null ? BigDecimal.ZERO : cost, quantity.multiply(cost == null ? BigDecimal.ZERO : cost), day, user);
            return;
        }
        BigDecimal left = quantity.negate();
        for (Map<String, Object> lot : jdbc.queryForList("SELECT lot_id, remaining_qty, unit_cost FROM ledger_lots WHERE thing_id = ? AND place_id = ? AND remaining_qty > 0 ORDER BY received_on, lot_id FOR UPDATE", thing, place)) {
            if (left.signum() <= 0) break;
            BigDecimal take = ((BigDecimal) lot.get("remaining_qty")).min(left), unit = (BigDecimal) lot.get("unit_cost");
            jdbc.update("UPDATE ledger_lots SET remaining_qty = remaining_qty - ? WHERE lot_id = ?", take, lot.get("lot_id"));
            jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES (?, 0, 0, 'OUT', ?, ?, ?, ?, ?, ?, ?, ?)",
                    source, thing, place, lot.get("lot_id"), take, unit, take.multiply(unit), day, user);
            left = left.subtract(take);
        }
        if (left.signum() > 0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "남은 수량이 모자랍니다 (줄이려는 수량이 남은 수량보다 " + shown(left) + " 많습니다).");
    }

    /** One lot set to what a count found: the difference goes into the ledger at the lot's own cost. */
    public void countLot(long lotId, BigDecimal counted, String user) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT thing_id, place_id, remaining_qty, unit_cost FROM ledger_lots WHERE lot_id = ? FOR UPDATE", lotId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT, "그 사이 그 묶음이 없어졌습니다. 다시 조회하세요.");
        BigDecimal book = (BigDecimal) rows.get(0).get("remaining_qty"), cost = (BigDecimal) rows.get(0).get("unit_cost"), difference = counted.subtract(book);
        if (difference.signum() == 0) return;
        open(RecordController.today(), "실사 차이를 반영할 수 없습니다");
        // found more than the books say: the lot (and what it is said to have received) grows; found less: it shrinks
        jdbc.update("UPDATE ledger_lots SET remaining_qty = ?, received_qty = received_qty + GREATEST(?, 0) WHERE lot_id = ?", counted, difference, lotId);
        jdbc.update("INSERT INTO ledger_moves (entity_key, record_id, line_no, direction, thing_id, place_id, lot_id, quantity, unit_cost, amount, moved_on, created_by) VALUES ('_count', 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                difference.signum() > 0 ? "IN" : "OUT", rows.get(0).get("thing_id"), rows.get(0).get("place_id"), lotId, difference.abs(), cost, difference.abs().multiply(cost), java.sql.Date.valueOf(RecordController.today()), user);
    }
    /** The cost the newest lot of an item in a warehouse came in at (what stock found by a count is valued at when nothing else is said). */
    public BigDecimal lastCost(long thing, long place) {
        List<BigDecimal> rows = jdbc.queryForList("SELECT unit_cost FROM ledger_lots WHERE thing_id = ? AND place_id = ? ORDER BY received_on DESC, lot_id DESC LIMIT 1", BigDecimal.class, thing, place);
        return rows.isEmpty() ? BigDecimal.ZERO : rows.get(0);
    }

    /** The lots and the cost a record's movements used, line by line (shown with the record and handed to the accounts). */
    public List<Map<String, Object>> moves(String entity, long id) {
        return jdbc.query("SELECT m.line_no, m.direction, l.lot_no, m.quantity, m.unit_cost, m.amount FROM ledger_moves m JOIN ledger_lots l ON l.lot_id = m.lot_id WHERE m.entity_key = ? AND m.record_id = ? ORDER BY m.line_no, m.move_id", (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("line", row.getInt("line_no")); out.put("direction", row.getString("direction")); out.put("lot", row.getString("lot_no"));
            out.put("quantity", row.getBigDecimal("quantity")); out.put("unitCost", row.getBigDecimal("unit_cost")); out.put("amount", row.getBigDecimal("amount"));
            return out;
        }, entity, id);
    }
}
