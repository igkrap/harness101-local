package com.example.localinventory.framework.app;

import com.example.localinventory.framework.system.SystemAccessService;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Screens that only show another entity's records in another shape: a month calendar, a tree. They store nothing.
 * Each has its own path (/api/calendar/{key}, /api/tree/{key}), so who may look is decided by who is given that screen.
 */
@RestController
public class ViewController {
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    private final SystemAccessService access;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    private final RecordStore store;
    public ViewController(AppDefinitions definitions, JdbcTemplate jdbc, SystemAccessService access, RecordStore store) { this.definitions = definitions; this.jdbc = jdbc; this.access = access; this.store = store; }

    private AppDefinitions.Definition screen(String key, Authentication authentication) {
        AppDefinitions.Stored stored = definitions.find(key);
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        if (stored == null || (!stored.status().equals("PUBLISHED") && !admin)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "화면을 찾지 못했습니다: " + key);
        return stored.definition();
    }
    private AppDefinitions.Stored source(String entity) {
        AppDefinitions.Stored stored = definitions.find(entity);
        if (stored == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "보여 줄 자료 " + entity + " 의 화면이 없어졌습니다.");
        return stored;
    }
    private static String text(JsonNode data, String name) { return data.hasNonNull(name) ? data.get(name).asString() : null; }

    /** How a record reads in one line: the named field, or its first field; a field that points at another record reads as that record's name. */
    private String label(AppDefinitions.Definition source, String name, JsonNode data, Map<String, Map<Long, String>> names) {
        AppDefinitions.Field field = name == null ? source.fields().get(0) : source.field(name);
        if (field == null || !data.hasNonNull(field.name())) return "";
        if (field.ref() != null) return names.computeIfAbsent(field.name(), ignored -> new LinkedHashMap<>()).computeIfAbsent(data.get(field.name()).asLong(), id -> {
            String code = definitions.codeField(field.ref());
            List<Map<String, Object>> rows = jdbc.queryForList("SELECT data->>? AS name, data->>? AS code FROM " + store.source(field.ref().entity()) + " app_records WHERE entity_key = ? AND id = ?", field.ref().label(), code == null ? "" : code, field.ref().entity(), id);
            if (rows.isEmpty()) return String.valueOf(id);
            return ((code == null || rows.get(0).get("code") == null ? "" : rows.get(0).get("code") + " ") + (rows.get(0).get("name") == null ? "" : rows.get(0).get("name"))).trim();
        });
        return data.get(field.name()).asString();
    }

    /** The records of one month (month=2026-11; this month when not given): those whose date - or period, with an end date - touches it. */
    @GetMapping("/api/calendar/{key}")
    public Map<String, Object> calendar(@PathVariable String key, @RequestParam(required = false) String month, Authentication authentication) {
        AppDefinitions.Definition screen = screen(key, authentication);
        if (screen.calendar() == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "달력 화면이 아닙니다: " + key);
        AppDefinitions.Calendar calendar = screen.calendar();
        AppDefinitions.Stored stored = source(calendar.entity());
        AppDefinitions.Definition source = stored.definition();
        java.time.YearMonth shown;
        try { shown = month == null || month.isBlank() ? java.time.YearMonth.from(RecordController.today()) : java.time.YearMonth.parse(month.trim()); }
        catch (java.time.format.DateTimeParseException error) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "month 는 2026-11 같은 모양입니다."); }
        String first = shown.atDay(1).toString(), last = shown.atEndOfMonth().toString();
        String ending = calendar.end() == null ? calendar.date() : calendar.end();
        Map<String, Map<Long, String>> names = new LinkedHashMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        jdbc.query("SELECT id, data::text AS data, status FROM " + store.source(calendar.entity()) + " app_records WHERE entity_key = ? AND data->>? <= ? AND COALESCE(data->>?, data->>?) >= ? ORDER BY data->>?, id LIMIT 3000", row -> {
            JsonNode data = mapper.readTree(row.getString("data"));
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", row.getLong("id"));
            item.put("date", text(data, calendar.date()));
            item.put("end", calendar.end() == null ? null : text(data, calendar.end()));
            item.put("label", label(source, calendar.label(), data, names));
            if (source.status() != null) { item.put("status", row.getString("status")); item.put("statusLabel", source.status().label(row.getString("status"))); }
            items.add(item);
        }, calendar.entity(), calendar.date(), last, ending, calendar.date(), first, calendar.date());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("month", shown.toString());
        out.put("entity", calendar.entity());
        out.put("programCode", stored.programCode());
        out.put("sourceTitle", source.title());
        out.put("items", items);
        return out;
    }

    /**
     * The hierarchy as a flat list the screen folds into a tree. Own-parent trees: nodes {id, parent, label, values}.
     * Pair trees (parent and child both point at another entity): edges {parent, child, values} and the names of the records they join.
     */
    @GetMapping("/api/tree/{key}")
    public Map<String, Object> tree(@PathVariable String key, Authentication authentication) {
        AppDefinitions.Definition screen = screen(key, authentication);
        if (screen.tree() == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "트리 화면이 아닙니다: " + key);
        AppDefinitions.Tree tree = screen.tree();
        AppDefinitions.Stored stored = source(tree.entity());
        AppDefinitions.Definition source = stored.definition();
        Map<String, Map<Long, String>> names = new LinkedHashMap<>();
        List<Map<String, Object>> columns = new ArrayList<>();
        for (String name : tree.columns()) { AppDefinitions.Field field = source.field(name); if (field != null) columns.add(Map.of("name", name, "label", field.label(), "type", field.type())); }
        List<Map<String, Object>> nodes = new ArrayList<>(), edges = new ArrayList<>();
        Map<String, String> joined = new LinkedHashMap<>();
        jdbc.query("SELECT id, data::text AS data FROM " + store.source(tree.entity()) + " app_records WHERE entity_key = ? ORDER BY id LIMIT 20000", row -> {
            JsonNode data = mapper.readTree(row.getString("data"));
            Map<String, Object> values = new LinkedHashMap<>();
            for (String name : tree.columns()) {
                AppDefinitions.Field field = source.field(name);
                if (field != null) values.put(name, field.ref() != null ? label(source, name, data, names) : data.hasNonNull(name) ? (data.get(name).isNumber() ? (Object) data.get(name).numberValue() : data.get(name).asString()) : null);
            }
            Map<String, Object> item = new LinkedHashMap<>();
            if (tree.child() == null) {
                item.put("id", row.getLong("id"));
                item.put("parent", data.hasNonNull(tree.parent()) ? data.get(tree.parent()).asLong() : null);
                item.put("label", label(source, tree.label(), data, names));
                item.put("values", values);
                nodes.add(item);
            } else if (data.hasNonNull(tree.parent()) && data.hasNonNull(tree.child())) {
                item.put("id", row.getLong("id"));
                item.put("parent", data.get(tree.parent()).asLong());
                item.put("child", data.get(tree.child()).asLong());
                item.put("values", values);
                edges.add(item);
                joined.put(String.valueOf(data.get(tree.parent()).asLong()), label(source, tree.parent(), data, names));
                joined.put(String.valueOf(data.get(tree.child()).asLong()), label(source, tree.child(), data, names));
            }
        }, tree.entity());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("entity", tree.entity());
        out.put("programCode", stored.programCode());
        out.put("sourceTitle", source.title());
        out.put("columns", columns);
        if (tree.child() == null) out.put("nodes", nodes); else { out.put("edges", edges); out.put("names", joined); }
        return out;
    }
}
