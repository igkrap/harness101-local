package com.example.localinventory.framework.app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/** Reading the stock: what there is now (by item and warehouse, with its value), the lots behind it, and the ledger of movements. */
@RestController
public class LedgerController {
    private final JdbcTemplate jdbc;
    private final AppDefinitions definitions;
    private final RecordStore store;
    private final QuantityLedger quantities;
    private final tools.jackson.databind.ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    public LedgerController(JdbcTemplate jdbc, AppDefinitions definitions, RecordStore store, QuantityLedger quantities) { this.jdbc = jdbc; this.definitions = definitions; this.store = store; this.quantities = quantities; }

    /** A record of another screen in a few words: its first two text fields (code and name). */
    private String name(String entity, Object id, Map<String, String> known) {
        if (entity == null || id == null) return "";
        return known.computeIfAbsent(entity + ":" + id, ignored -> {
            AppDefinitions.Stored stored = definitions.find(entity);
            if (stored == null) return String.valueOf(id);
            List<String> rows = jdbc.queryForList("SELECT data::text FROM " + store.source(entity) + " app_records WHERE id = ?", String.class, ((Number) id).longValue());
            if (rows.isEmpty()) return "(지워진 자료 " + id + ")";
            JsonNode data = mapper.readTree(rows.get(0));
            List<String> parts = new ArrayList<>();
            for (AppDefinitions.Field field : stored.definition().fields())
                if (parts.size() < 2 && field.wordy() && !field.type().equals("memo") && data.hasNonNull(field.name())) parts.add(data.get(field.name()).asString());
            return String.join(" ", parts);
        });
    }
    private static Long id(String text) { return text != null && text.trim().matches("\\d{1,18}") ? Long.valueOf(text.trim()) : null; }

    public record Adjust(String thingEntity, Long thingId, String placeEntity, Long placeId, java.math.BigDecimal quantity, java.math.BigDecimal unitCost, String lot) {}
    private static final Map<String, String> OWN = Map.of("_adjust", "수량 넣기·빼기");

    /** Opening stock or a counted difference: +quantity at a unit cost makes a lot, -quantity is taken from the oldest lots. */
    @org.springframework.web.bind.annotation.PostMapping("/api/system/ledger/adjust")
    @org.springframework.transaction.annotation.Transactional
    public List<Map<String, Object>> adjust(@org.springframework.web.bind.annotation.RequestBody Adjust request, org.springframework.security.core.Authentication authentication) {
        if (request.thingId() == null || request.placeId() == null || request.quantity() == null || request.quantity().signum() == 0 || request.thingEntity() == null || request.placeEntity() == null)
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "대상, 위치, 수량(0 이 아닌 수)을 적어 주세요.");
        if (!store.has(request.thingEntity(), request.thingId()) || !store.has(request.placeEntity(), request.placeId()))
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "대상이나 위치 자료를 찾지 못했습니다.");
        if (request.unitCost() != null && request.unitCost().signum() < 0) throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "단가는 0 이상이어야 합니다.");
        quantities.adjust(request.thingEntity(), request.thingId(), request.placeEntity(), request.placeId(), request.quantity(), request.unitCost(), authentication.getName(), "_adjust", request.lot());
        return balance(String.valueOf(request.thingId()), String.valueOf(request.placeId()), null);
    }

    /** Ledger rows of items that are no longer there (an item deleted after its stock was used up, records made only to try something): removed. Administrators. */
    @org.springframework.web.bind.annotation.DeleteMapping("/api/system/ledger/orphans")
    @org.springframework.transaction.annotation.Transactional
    public Map<String, Object> orphans() {
        int moves = 0, lots = 0;
        for (Map<String, Object> row : jdbc.queryForList("SELECT DISTINCT thing_entity, thing_id FROM ledger_lots")) {
            String entity = (String) row.get("thing_entity"); long thing = ((Number) row.get("thing_id")).longValue();
            if (store.has(entity, thing)) continue;
            String through = quantities.closedThrough();         // what a closed month holds is left as it is
            if (through != null && jdbc.queryForObject("SELECT COUNT(*) FROM ledger_moves m JOIN ledger_lots l ON l.lot_id = m.lot_id WHERE l.thing_entity = ? AND l.thing_id = ? AND m.moved_on < ?",
                    Integer.class, entity, thing, java.sql.Date.valueOf(java.time.YearMonth.parse(through).plusMonths(1).atDay(1))) > 0) continue;
            moves += jdbc.update("DELETE FROM ledger_moves WHERE thing_id = ? AND lot_id IN (SELECT lot_id FROM ledger_lots WHERE thing_entity = ? AND thing_id = ?)", thing, entity, thing);
            lots += jdbc.update("DELETE FROM ledger_lots WHERE thing_entity = ? AND thing_id = ?", entity, thing);
        }
        return Map.of("moves", moves, "lots", lots);
    }

    /** What was held at the end of a closed month of a lock group: per thing and place, quantity and value (each lot at its own cost). */
    @GetMapping("/api/ledger/month-end/{group}/{period}")
    public List<Map<String, Object>> monthEnd(@org.springframework.web.bind.annotation.PathVariable String group, @org.springframework.web.bind.annotation.PathVariable String period) {
        if (!period.matches("\\d{4}-(0[1-9]|1[0-2])")) throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "달은 2026-10 같은 모양으로 적습니다.");
        Map<String, String> names = new LinkedHashMap<>();
        return jdbc.query("SELECT l.thing_entity, b.thing_id, l.place_entity, b.place_id, SUM(b.quantity) AS quantity, SUM(b.amount) AS amount, COUNT(*) AS lots "
                + "FROM ledger_month_end b JOIN ledger_lots l ON l.lot_id = b.lot_id WHERE b.lock_group = ? AND b.period = ? "
                + "GROUP BY l.thing_entity, b.thing_id, l.place_entity, b.place_id ORDER BY b.thing_id, b.place_id", (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("thing", name(row.getString("thing_entity"), row.getLong("thing_id"), names));
            out.put("place", name(row.getString("place_entity"), row.getLong("place_id"), names));
            out.put("quantity", row.getBigDecimal("quantity")); out.put("amount", row.getBigDecimal("amount")); out.put("lots", row.getInt("lots"));
            return out;
        }, group, period);
    }

    /** What is in stock now: per item and warehouse, the quantity, its value (each lot at its own cost) and how many lots hold it. */
    @GetMapping("/api/ledger/balance")
    public List<Map<String, Object>> balance(@RequestParam(required = false) String thing, @RequestParam(required = false) String place, @RequestParam(required = false) String entity) {
        Map<String, String> names = new LinkedHashMap<>();
        return jdbc.query("SELECT thing_entity, thing_id, place_entity, place_id, SUM(remaining_qty) AS quantity, SUM(remaining_qty * unit_cost) AS amount, COUNT(*) AS lots FROM ledger_lots "
                + "WHERE remaining_qty > 0 AND (CAST(? AS bigint) IS NULL OR thing_id = ?) AND (CAST(? AS bigint) IS NULL OR place_id = ?) AND (CAST(? AS varchar) IS NULL OR thing_entity = ?) GROUP BY thing_entity, thing_id, place_entity, place_id ORDER BY thing_id, place_id LIMIT 5000", (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("thingId", row.getLong("thing_id")); out.put("thing", name(row.getString("thing_entity"), row.getLong("thing_id"), names));
            out.put("placeId", row.getLong("place_id")); out.put("place", name(row.getString("place_entity"), row.getLong("place_id"), names));
            out.put("quantity", row.getBigDecimal("quantity")); out.put("amount", row.getBigDecimal("amount")); out.put("lots", row.getInt("lots"));
            out.put("tracking", quantities.tracking(row.getString("thing_entity"), row.getLong("thing_id")));
            return out;
        }, id(thing), id(thing), id(place), id(place), entity, entity);
    }

    /** The lots (those with something left, unless all=true), oldest first: the order they are issued in. */
    @GetMapping({"/api/ledger/lots", "/api/auth/ledger/lots"})       // (the lot window of any screen that issues stock reads it too)
    public List<Map<String, Object>> lots(@RequestParam(required = false) String thing, @RequestParam(required = false) String place, @RequestParam(defaultValue = "false") boolean all, @RequestParam(required = false) String entity) {
        Map<String, String> names = new LinkedHashMap<>();
        return jdbc.query("SELECT * FROM ledger_lots WHERE (? OR remaining_qty > 0) AND (CAST(? AS bigint) IS NULL OR thing_id = ?) AND (CAST(? AS bigint) IS NULL OR place_id = ?) AND (CAST(? AS varchar) IS NULL OR thing_entity = ?) ORDER BY received_on, lot_id LIMIT 5000", (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("lot", row.getString("lot_no")); out.put("thing", name(row.getString("thing_entity"), row.getLong("thing_id"), names));
            out.put("place", name(row.getString("place_entity"), row.getLong("place_id"), names));
            out.put("receivedOn", row.getDate("received_on").toString()); out.put("unitCost", row.getBigDecimal("unit_cost"));
            out.put("received", row.getBigDecimal("received_qty")); out.put("remaining", row.getBigDecimal("remaining_qty"));
            out.put("amount", row.getBigDecimal("remaining_qty").multiply(row.getBigDecimal("unit_cost")));
            AppDefinitions.Stored source = definitions.find(row.getString("source_entity"));
            out.put("source", source == null ? OWN.getOrDefault(row.getString("source_entity"), row.getString("source_entity")) : source.definition().title()); out.put("sourceEntity", row.getString("source_entity")); out.put("sourceId", row.getLong("source_id"));
            return out;
        }, all, id(thing), id(thing), id(place), id(place), entity, entity);
    }

    /** The ledger: every movement in a period (newest first), with the lot it touched and its cost. */
    @GetMapping("/api/ledger/moves")
    public List<Map<String, Object>> moves(@RequestParam(required = false) String thing, @RequestParam(required = false) String place,
                                           @RequestParam(required = false) String from, @RequestParam(required = false) String to, @RequestParam(required = false) String entity) {
        Map<String, String> names = new LinkedHashMap<>();
        String first = from != null && from.matches("\\d{4}-\\d{2}-\\d{2}") ? from : "1900-01-01", last = to != null && to.matches("\\d{4}-\\d{2}-\\d{2}") ? to : "2999-12-31";
        return jdbc.query("SELECT m.*, l.lot_no, l.thing_entity, l.place_entity FROM ledger_moves m JOIN ledger_lots l ON l.lot_id = m.lot_id WHERE m.moved_on BETWEEN CAST(? AS date) AND CAST(? AS date) "
                + "AND (CAST(? AS bigint) IS NULL OR m.thing_id = ?) AND (CAST(? AS bigint) IS NULL OR m.place_id = ?) AND (CAST(? AS varchar) IS NULL OR l.thing_entity = ?) ORDER BY m.moved_on DESC, m.move_id DESC LIMIT 5000", (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("movedOn", row.getDate("moved_on").toString()); out.put("direction", row.getString("direction")); out.put("lot", row.getString("lot_no"));
            out.put("thing", name(row.getString("thing_entity"), row.getLong("thing_id"), names)); out.put("place", name(row.getString("place_entity"), row.getLong("place_id"), names));
            out.put("quantity", row.getBigDecimal("quantity")); out.put("unitCost", row.getBigDecimal("unit_cost")); out.put("amount", row.getBigDecimal("amount"));
            AppDefinitions.Stored source = definitions.find(row.getString("entity_key"));
            out.put("source", source == null ? OWN.getOrDefault(row.getString("entity_key"), row.getString("entity_key")) : source.definition().title()); out.put("sourceEntity", row.getString("entity_key")); out.put("sourceId", row.getLong("record_id"));
            out.put("by", row.getString("created_by"));
            return out;
        }, first, last, id(thing), id(thing), id(place), id(place), entity, entity);
    }
}
