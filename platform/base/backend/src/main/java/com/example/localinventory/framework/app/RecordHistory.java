package com.example.localinventory.framework.app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The history of records: every registration, change, status action and deletion is written down as it happens
 * (in the same transaction, so a change that is refused leaves no trace), and read back as plain sentences -
 * which field went from what to what, in the words the screens use.
 */
@Service
public class RecordHistory {
    private final JdbcTemplate jdbc;
    private final AppDefinitions definitions;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    private final RecordStore store;
    public RecordHistory(JdbcTemplate jdbc, AppDefinitions definitions, RecordStore store) { this.jdbc = jdbc; this.definitions = definitions; this.store = store; }

    /** before/after: the record's values as JSON text (null when there is none). The screen's own history table keeps the record as it
     *  stands after what was done (as it was before, for a deletion); what changed is read by setting each row against the one before it. */
    public void note(String entity, long id, String action, String actionName, boolean automatic, String before, String after, String statusBefore, String statusAfter, String user) {
        AppDefinitions.Stored stored = definitions.find(entity);
        if (stored == null || !RecordStore.keeps(stored.definition())) return;
        String record = after != null ? after : before != null ? before : store.data(entity, id);
        store.noteHistory(stored.definition(), id, action, actionName, automatic, record, statusBefore, statusAfter, user, null);
    }

    /** The record's values as stored now (for "before"). */
    public String stored(String entity, long id) {
        return store.data(entity, id);
    }

    private Map<String, Object> entry(AppDefinitions.Definition definition, Map<String, Object> row, String beforeData, String afterData, Map<String, Map<String, String>> names) {
        Map<String, Object> out = new LinkedHashMap<>();
        String action = (String) row.get("action"), actionName = (String) row.get("action_name");
        out.put("at", ((java.sql.Timestamp) row.get("changed_at")).toLocalDateTime().toString());
        out.put("by", row.get("changed_by"));
        out.put("action", action);
        out.put("automatic", Boolean.TRUE.equals(row.get("automatic")));
        out.put("what", switch (action) { case "CREATE" -> "등록"; case "DELETE" -> "삭제"; case "STATUS" -> definition == null ? actionName : actionLabel(definition, actionName);
            case "FILE_ADD" -> "첨부 추가"; case "FILE_REMOVE" -> "첨부 삭제"; default -> "수정"; });
        List<Map<String, Object>> changes = new ArrayList<>();
        if (action.equals("STATUS") && definition != null && definition.status() != null)
            changes.add(change("상태", definition.status().label((String) row.get("status_before")), definition.status().label((String) row.get("status_after"))));
        if (action.equals("FILE_ADD")) changes.add(change("파일", "", actionName));
        if (action.equals("FILE_REMOVE")) changes.add(change("파일", actionName, ""));
        if (action.equals("DELETE") && definition != null && afterData != null) {          // what it held when it was deleted
            JsonNode gone = mapper.readTree(afterData);
            for (AppDefinitions.Field field : definition.fields()) {
                String was = shown(field, gone.get(field.name()), names);
                if (!was.isEmpty()) changes.add(change(field.label(), was, ""));
            }
        }
        if (action.equals("UPDATE") && definition != null && beforeData != null && afterData != null) {
            JsonNode before = mapper.readTree(beforeData), after = mapper.readTree(afterData);
            compare(definition.fields(), before, after, "", changes, names);
            for (AppDefinitions.LineSet set : definition.lineSets()) lines(new AppDefinitions.Lines(set.label(), set.fields(), set.min(), set.max()), before.path(set.name()), after.path(set.name()), changes, names);
        }
        out.put("changes", changes);
        return out;
    }

    /** Newest first. Each entry: at, by, what (등록, 수정, 확정 ...), automatic, changes [{label, before, after}] - the row set against the one before it. */
    public List<Map<String, Object>> read(AppDefinitions.Definition definition, long id) {
        Map<String, Map<String, String>> names = new LinkedHashMap<>();
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT h.action, h.action_name, h.automatic, h.status_before, h.status_after, h.changed_by, h.changed_at, "
                + RecordStore.historyJson(definition) + "::text AS data FROM " + RecordStore.historyTable(definition.key()) + " h WHERE h.record_id = ? ORDER BY h.hist_id", id);
        List<Map<String, Object>> out = new ArrayList<>();
        String previous = null;
        for (Map<String, Object> row : rows) {
            String now = (String) row.get("data");
            out.add(entry(definition, row, previous, now, names));
            if (!"DELETE".equals(row.get("action"))) previous = now;
        }
        java.util.Collections.reverse(out);
        return out.size() > 500 ? out.subList(0, 500) : out;
    }

    private static String actionLabel(AppDefinitions.Definition definition, String name) {
        if (definition.status() == null || name == null) return "상태 변경";
        return definition.status().actions().stream().filter(action -> action.name().equals(name)).map(AppDefinitions.Action::label).findFirst().orElse(name);
    }

    private static Map<String, Object> change(String label, String before, String after) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("label", label); out.put("before", before); out.put("after", after);
        return out;
    }

    private void compare(List<AppDefinitions.Field> fields, JsonNode before, JsonNode after, String where, List<Map<String, Object>> changes, Map<String, Map<String, String>> names) {
        for (AppDefinitions.Field field : fields) {
            String was = shown(field, before.get(field.name()), names), now = shown(field, after.get(field.name()), names);
            if (!was.equals(now)) changes.add(change(where + field.label(), was, now));
        }
    }

    /** Lines are told apart by their place: line 2 before is set against line 2 after; extra ones were added or removed. */
    private void lines(AppDefinitions.Lines lines, JsonNode before, JsonNode after, List<Map<String, Object>> changes, Map<String, Map<String, String>> names) {
        int was = before.isArray() ? before.size() : 0, now = after.isArray() ? after.size() : 0;
        for (int index = 0; index < Math.max(was, now); index++) {
            String where = lines.label() + " " + (index + 1) + "번째 줄";
            if (index >= was) changes.add(change(where, "", "추가: " + line(lines, after.get(index), names)));
            else if (index >= now) changes.add(change(where, line(lines, before.get(index), names), "삭제"));
            else compare(lines.fields(), before.get(index), after.get(index), where + " ", changes, names);
        }
    }

    private String line(AppDefinitions.Lines lines, JsonNode row, Map<String, Map<String, String>> names) {
        List<String> parts = new ArrayList<>();
        for (AppDefinitions.Field field : lines.fields()) { String value = shown(field, row.get(field.name()), names); if (!value.isEmpty()) parts.add(field.label() + " " + value); }
        return String.join(", ", parts);
    }

    /** A stored value as the screens show it: numbers with separators, dates with slashes, names for codes and for other screens' records. */
    private String shown(AppDefinitions.Field field, JsonNode value, Map<String, Map<String, String>> names) {
        if (field.type().equals("yesno")) return value != null && value.asBoolean(false) ? "예" : "아니오";
        if (value == null || value.isNull()) return "";
        switch (field.type()) {
            case "number": {
                java.text.DecimalFormat format = new java.text.DecimalFormat(field.decimals() == null ? "#,##0.######" : "#,##0" + (field.decimals() > 0 ? "." + "0".repeat(field.decimals()) : ""),
                        java.text.DecimalFormatSymbols.getInstance(java.util.Locale.US));
                return value.isNumber() ? format.format(value.asDouble()) : value.asString();
            }
            case "date": return value.asString().replace('-', '/');
            case "code": {
                Map<String, String> known = names.computeIfAbsent("code:" + field.codeGroup(), ignored -> {
                    Map<String, String> out = new LinkedHashMap<>();
                    for (Map<String, Object> row : jdbc.queryForList("SELECT code, code_name FROM sys_codes WHERE group_code = ?", field.codeGroup())) out.put((String) row.get("code"), (String) row.get("code_name"));
                    return out;
                });
                return known.getOrDefault(value.asString(), value.asString());
            }
            case "ref": {
                String key = value.asString();
                Map<String, String> known = names.computeIfAbsent("ref:" + field.ref().entity() + ":" + field.ref().label(), ignored -> new LinkedHashMap<>());
                return known.computeIfAbsent(key, ignored -> {
                    String code = definitions.codeField(field.ref());
                    List<Map<String, Object>> rows = jdbc.queryForList("SELECT data->>? AS name, data->>? AS code FROM " + store.source(field.ref().entity()) + " app_records WHERE entity_key = ? AND id = ?",
                            field.ref().label(), code == null ? "" : code, field.ref().entity(), value.asLong());
                    if (rows.isEmpty()) return "(지워진 자료 " + key + ")";
                    Object name = rows.get(0).get("name"), shownCode = code == null ? null : rows.get(0).get("code");
                    return ((shownCode == null ? "" : shownCode + " ") + (name == null ? "" : name)).trim();
                });
            }
            default: return value.asString();
        }
    }
}
