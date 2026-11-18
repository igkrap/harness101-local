package com.example.localinventory.framework.app;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;

/**
 * Where the records of defined screens are kept: every screen has a real table of its own, with a typed column per field,
 * and one more table per table of lines.
 *
 *   r_<key>            id, status, created_by, created_at, updated_by, updated_at, f_<field> ...
 *   r_<key>__<lines>   id, record_id -> r_<key>(id) (removed with it), line_no, f_<field> ...
 *
 * text, memo, serial -> TEXT; code -> VARCHAR(50); number -> NUMERIC; date -> DATE; time -> TIME; yesno -> BOOLEAN;
 * ref -> BIGINT (the id of the other screen's record). Fields that point elsewhere, that are asked by, dates and numbers
 * given on save are indexed. Ids come from one sequence for all screens (app_record_ids), so a record's id never repeats anywhere.
 *
 * The definition decides the tables: saving a definition makes the table or adds what is missing (ensure). A field
 * taken out of a definition keeps its column, unused, so putting it back (an undo) brings its values back; nothing is
 * dropped until the screen itself is removed.
 *
 * Readers that want a record whole get it as JSON, built by the database from the columns (source, json): the same
 * shape the screens and the rules always worked with, {field: value, lines: [{...}]}.
 */
@Service
public class RecordStore {
    private static final Logger log = LoggerFactory.getLogger(RecordStore.class);
    private final JdbcTemplate jdbc;
    private final AppDefinitions definitions;
    public RecordStore(JdbcTemplate jdbc, AppDefinitions definitions) { this.jdbc = jdbc; this.definitions = definitions; }

    /** Whether a definition keeps records of its own (a summary, a work screen, a calendar ... keeps none). */
    public static boolean keeps(AppDefinitions.Definition definition) {
        return definition != null && definition.fields() != null && !definition.fields().isEmpty() && definition.summary() == null && definition.dashboard() == null
                && definition.over() == null && definition.calendar() == null && definition.tree() == null && definition.take() == null && definition.ledgerView() == null;
    }

    private static String snake(String name) { return name.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase(); }
    /** A name the database takes (63 characters): a long one is cut and told apart by a few letters of its hash. */
    private static String fitted(String name) {
        if (name.length() <= 60) return name;
        return name.substring(0, 50) + "_" + Integer.toHexString(name.hashCode() & 0x7fffffff);
    }
    public static String table(String key) { return fitted("r_" + key); }
    public static String lineTable(String key, String set) { return fitted("r_" + key + "__" + snake(set)); }
    public static String column(String field) { return fitted("f_" + snake(field)); }
    /** The screen's history: one row per registration, change, status action or deletion, holding the record as it was then (h_<key>). */
    public static String historyTable(String key) { return fitted("h_" + key); }
    public static String sqlType(AppDefinitions.Field field) {
        return switch (field.type()) {
            case "number" -> "numeric";
            case "date" -> "date";
            case "time" -> "time without time zone";
            case "yesno" -> "boolean";
            case "ref" -> "bigint";
            case "code" -> "character varying";
            default -> "text";
        };
    }
    private static boolean indexed(AppDefinitions.Field field) { return field.ref() != null || field.search() || field.type().equals("serial") || field.type().equals("date") || field.unique(); }

    private boolean exists(String table) {
        Integer found = jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", Integer.class, table);
        return found != null && found > 0;
    }

    /** Make the screen's tables, or bring them up to its definition: missing columns are added, a column whose field changed kind is converted. */
    public void ensure(AppDefinitions.Definition definition) {
        if (!keeps(definition)) return;
        String table = table(definition.key());
        if (!exists(table))
            jdbc.execute("CREATE TABLE " + table + " (id BIGINT PRIMARY KEY DEFAULT nextval('app_record_ids'), status VARCHAR(30), created_by VARCHAR(100), "
                    + "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_by VARCHAR(100), updated_at TIMESTAMP)");
        columns(table, definition.fields());
        for (AppDefinitions.LineSet set : definition.lineSets()) {
            String lines = lineTable(definition.key(), set.name());
            if (!exists(lines)) {
                jdbc.execute("CREATE TABLE " + lines + " (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, record_id BIGINT NOT NULL REFERENCES " + table + "(id) ON DELETE CASCADE, line_no INT NOT NULL)");
                jdbc.execute("CREATE INDEX " + fitted("ix_" + lines + "_record") + " ON " + lines + " (record_id, line_no)");
            }
            columns(lines, set.fields());
        }
        String history = historyTable(definition.key());
        if (!exists(history)) {
            jdbc.execute("CREATE TABLE " + history + " (hist_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, record_id BIGINT NOT NULL, action VARCHAR(20) NOT NULL, "
                    + "action_name VARCHAR(300), automatic BOOLEAN NOT NULL DEFAULT FALSE, status_before VARCHAR(30), status_after VARCHAR(30), "
                    + "changed_by VARCHAR(100), changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, lines_data JSONB)");
            jdbc.execute("CREATE INDEX " + fitted("ix_" + history + "_record") + " ON " + history + " (record_id, hist_id)");
        }
        historyColumns(history, definition.fields());
    }

    /** The history keeps the screen's columns too; a value an old row holds that the new kind cannot read keeps the column as text. */
    private void historyColumns(String table, List<AppDefinitions.Field> fields) {
        Map<String, String> held = new LinkedHashMap<>();
        jdbc.query("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                row -> { held.put(row.getString("column_name"), row.getString("data_type")); }, table);
        for (AppDefinitions.Field field : fields) {
            String column = column(field.name()), type = sqlType(field);
            if (!held.containsKey(column)) jdbc.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + type);
            else if (!held.get(column).equals(type) && !held.get(column).equals("text")) {
                String using = type.equals("text") || type.equals("character varying") ? column + "::text" : "NULLIF(" + column + "::text, '')::" + type;
                try { jdbc.execute("ALTER TABLE " + table + " ALTER COLUMN " + column + " TYPE " + type + " USING " + using); }
                catch (org.springframework.dao.DataAccessException kept) { jdbc.execute("ALTER TABLE " + table + " ALTER COLUMN " + column + " TYPE text USING " + column + "::text"); }
            }
        }
    }

    /** One row of the screen's history: what was done, by whom, and the record (as JSON) as it stands after it - before it, for a deletion. */
    public void noteHistory(AppDefinitions.Definition definition, long id, String action, String actionName, boolean automatic, String record,
                            String statusBefore, String statusAfter, String user, java.sql.Timestamp at) {
        List<String> columns = new ArrayList<>(List.of("record_id", "action", "action_name", "automatic", "status_before", "status_after", "changed_by", "changed_at", "lines_data"));
        List<String> values = new ArrayList<>(List.of("?", "?", "?", "?", "?", "?", "?", "COALESCE(?, CURRENT_TIMESTAMP)"));
        List<String> sets = new ArrayList<>();
        for (AppDefinitions.LineSet set : definition.lineSets()) sets.add("'" + set.name() + "', s.j->'" + set.name() + "'");
        values.add(sets.isEmpty() ? "NULL" : "jsonb_build_object(" + String.join(", ", sets) + ")");
        for (AppDefinitions.Field field : definition.fields()) {
            columns.add(column(field.name()));
            String text = "s.j->>'" + field.name() + "'", type = sqlType(field);
            values.add(type.equals("text") || type.equals("character varying") ? text : "NULLIF(" + text + ", '')::" + type);
        }
        jdbc.update("INSERT INTO " + historyTable(definition.key()) + " (" + String.join(", ", columns) + ") SELECT " + String.join(", ", values)
                + " FROM (SELECT CAST(? AS jsonb) AS j) s", id, action, actionName, automatic, statusBefore, statusAfter, user, at, record == null ? "{}" : record);
    }
    /** The SQL that reads a history row (alias h) as the record's JSON then, its lines included. */
    public static String historyJson(AppDefinitions.Definition definition) {
        return "(" + pairs(definition.fields(), "h") + " || COALESCE(h.lines_data, '{}'::jsonb))";
    }
    public void forgetHistory(String key, long id) {
        if (exists(historyTable(key))) jdbc.update("DELETE FROM " + historyTable(key) + " WHERE record_id = ?", id);
    }

    private void columns(String table, List<AppDefinitions.Field> fields) {
        Map<String, String> held = new LinkedHashMap<>();
        jdbc.query("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                row -> { held.put(row.getString("column_name"), row.getString("data_type")); }, table);
        Map<String, String> taken = new LinkedHashMap<>();
        for (AppDefinitions.Field field : fields) {
            String column = column(field.name()), type = sqlType(field);
            if (taken.put(column, field.name()) != null)
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "항목 " + field.name() + " 와(과) " + taken.get(column) + " 은(는) 대소문자만 달라 같은 열이 됩니다. 이름을 다르게 지으세요.");
            if (!held.containsKey(column)) jdbc.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + type);
            else if (!held.get(column).equals(type)) {
                // The field became another kind: the values it holds are read as the new kind, or the change is refused.
                String using = type.equals("text") || type.equals("character varying") ? column + "::text" : "NULLIF(" + column + "::text, '')::" + type;
                try { jdbc.execute("ALTER TABLE " + table + " ALTER COLUMN " + column + " TYPE " + type + " USING " + using); }
                catch (org.springframework.dao.DataAccessException refused) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "항목 " + field.label() + "(" + field.name() + ") 의 종류를 " + field.type() + " (으)로 바꿀 수 없습니다: 이미 들어 있는 값 중에 그 종류로 읽을 수 없는 것이 있습니다.");
                }
            }
            if (indexed(field)) jdbc.execute("CREATE INDEX IF NOT EXISTS " + fitted("ix_" + table + "_" + column.substring(2)) + " ON " + table + " (" + column + ")");
        }
    }

    /** Every table a screen has (its own and its lines'), by what the database holds. */
    private List<String> tablesOf(String key) {
        String table = table(key);
        return jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND (table_name = ? OR left(table_name, ?) = ?) ORDER BY length(table_name) DESC",
                String.class, table, table.length() + 2, table + "__");
    }
    /** The screen is gone: so are its tables. */
    public void drop(String key) {
        for (String table : tablesOf(key)) jdbc.execute("DROP TABLE IF EXISTS " + table + " CASCADE");
        jdbc.execute("DROP TABLE IF EXISTS " + historyTable(key));
    }
    public long count(String key) { return exists(table(key)) ? jdbc.queryForObject("SELECT COUNT(*) FROM " + table(key), Long.class) : 0; }
    public void clear(String key) { if (exists(table(key))) jdbc.update("DELETE FROM " + table(key)); }

    private static String pairs(List<AppDefinitions.Field> fields, String alias) {
        List<String> parts = new ArrayList<>();
        for (AppDefinitions.Field field : fields) parts.add("'" + field.name() + "', " + alias + "." + column(field.name()));
        // jsonb_build_object takes 100 arguments: a long list of fields is built in pieces and joined
        List<String> pieces = new ArrayList<>();
        for (int from = 0; from < parts.size(); from += 40) pieces.add("jsonb_build_object(" + String.join(", ", parts.subList(from, Math.min(parts.size(), from + 40))) + ")");
        return pieces.isEmpty() ? "'{}'::jsonb" : String.join(" || ", pieces);
    }
    /** The SQL that reads one row of the screen's table (alias t) as the record's JSON, its lines included. */
    public static String json(AppDefinitions.Definition definition) {
        StringBuilder out = new StringBuilder("(" + pairs(definition.fields(), "t"));
        for (AppDefinitions.LineSet set : definition.lineSets())
            out.append(" || jsonb_build_object('").append(set.name()).append("', COALESCE((SELECT jsonb_agg(jsonb_build_object('_line', l.id) || ").append(pairs(set.fields(), "l")).append(" ORDER BY l.line_no) FROM ")
                    .append(lineTable(definition.key(), set.name())).append(" l WHERE l.record_id = t.id), '[]'::jsonb))");
        return out.append(")").toString();
    }
    /** What to select from the screen's table (alias t) for a whole record. */
    public static String select(AppDefinitions.Definition definition) {
        return "t.id, " + json(definition) + "::text AS data, t.status, t.created_by, t.created_at, t.updated_by, t.updated_at";
    }
    /**
     * The screen's records as a table to read from, each row a whole record: (id, entity_key, data jsonb, status, created_by, ...).
     * Written into a query in place of a table name; a condition on id put on it is answered by the table's own index.
     */
    public String source(String key) {
        AppDefinitions.Stored stored = key != null && key.matches("[a-z][a-z0-9_]{1,39}") ? definitions.find(key) : null;
        if (stored == null || !keeps(stored.definition()) || !exists(table(key)))
            return "(SELECT NULL::bigint AS id, NULL::varchar AS entity_key, NULL::jsonb AS data, NULL::varchar AS status, NULL::varchar AS created_by, NULL::timestamp AS created_at, NULL::varchar AS updated_by, NULL::timestamp AS updated_at WHERE FALSE)";
        return "(SELECT t.id, '" + key + "'::varchar AS entity_key, " + json(stored.definition()) + " AS data, t.status, t.created_by, t.created_at, t.updated_by, t.updated_at FROM " + table(key) + " t)";
    }

    /** The record as JSON text, or null when there is none. */
    public String data(AppDefinitions.Definition definition, long id) {
        List<String> rows = jdbc.queryForList("SELECT " + json(definition) + "::text FROM " + table(definition.key()) + " t WHERE t.id = ?", String.class, id);
        return rows.isEmpty() ? null : rows.get(0);
    }
    public String data(String key, long id) {
        AppDefinitions.Stored stored = definitions.find(key);
        return stored == null || !keeps(stored.definition()) ? null : data(stored.definition(), id);
    }
    public String status(String key, long id) {
        List<String> rows = jdbc.queryForList("SELECT status FROM " + table(key) + " WHERE id = ?", String.class, id);
        return rows.isEmpty() ? null : rows.get(0);
    }
    public boolean has(String key, long id) {
        if (!exists(table(key))) return false;
        Integer found = jdbc.queryForObject("SELECT COUNT(*) FROM " + table(key) + " WHERE id = ?", Integer.class, id);
        return found != null && found > 0;
    }

    /** A value of a record as the database takes it for the field's column (always handed over as text and read as the column's kind). */
    private static String given(AppDefinitions.Field field, JsonNode value) {
        if (value == null || value.isNull()) return null;
        if (field.type().equals("yesno")) return String.valueOf(value.isBoolean() ? value.asBoolean() : "true".equalsIgnoreCase(value.asString()));
        if (value.isNumber()) return field.type().equals("ref") ? String.valueOf(value.asLong()) : new BigDecimal(value.asString()).stripTrailingZeros().toPlainString();
        String text = value.asString();
        return text.isEmpty() && !sqlType(field).equals("text") && !sqlType(field).equals("character varying") ? null : text;
    }
    private static String cast(AppDefinitions.Field field) { String type = sqlType(field); return type.equals("text") || type.equals("character varying") ? "?" : "CAST(? AS " + type + ")"; }

    /** id: null for a new record (the next id is given), or the id it must keep (records carried over from the old single table). */
    public long insert(AppDefinitions.Definition definition, JsonNode data, String status, String user, Long id) {
        List<String> names = new ArrayList<>(List.of("status", "created_by", "updated_by", "updated_at")), marks = new ArrayList<>(List.of("?", "?", "?", "CURRENT_TIMESTAMP"));
        List<Object> args = new ArrayList<>(java.util.Arrays.asList(status, user, user));
        if (id != null) { names.add("id"); marks.add("?"); args.add(id); }
        for (AppDefinitions.Field field : definition.fields()) { names.add(column(field.name())); marks.add(cast(field)); args.add(given(field, data.get(field.name()))); }
        Long made = jdbc.queryForObject("INSERT INTO " + table(definition.key()) + " (" + String.join(", ", names) + ") VALUES (" + String.join(", ", marks) + ") RETURNING id", Long.class, args.toArray());
        lines(definition, made, data);
        return made;
    }

    public void update(AppDefinitions.Definition definition, long id, JsonNode data, String user) {
        List<String> sets = new ArrayList<>(List.of("updated_by = ?", "updated_at = CURRENT_TIMESTAMP"));
        List<Object> args = new ArrayList<>(java.util.Arrays.asList(user));
        for (AppDefinitions.Field field : definition.fields()) { sets.add(column(field.name()) + " = " + cast(field)); args.add(given(field, data.get(field.name()))); }
        args.add(id);
        jdbc.update("UPDATE " + table(definition.key()) + " SET " + String.join(", ", sets) + " WHERE id = ?", args.toArray());
        lines(definition, id, data);
    }

    /**
     * Write the record's lines. A line that comes back with its id (_line) keeps it - it is changed in place - so what points at that line
     * (a step of a routing, a part of a BOM) keeps pointing at it; new lines are added, lines no longer there are removed.
     */
    private void lines(AppDefinitions.Definition definition, long id, JsonNode data) {
        for (AppDefinitions.LineSet set : definition.lineSets()) {
            String table = lineTable(definition.key(), set.name());
            List<String> names = new ArrayList<>(List.of("record_id", "line_no")), marks = new ArrayList<>(List.of("?", "?")), sets = new ArrayList<>(List.of("line_no = ?"));
            for (AppDefinitions.Field field : set.fields()) { names.add(column(field.name())); marks.add(cast(field)); sets.add(column(field.name()) + " = " + cast(field)); }
            String insert = "INSERT INTO " + table + " (" + String.join(", ", names) + ") VALUES (" + String.join(", ", marks) + ")";
            String change = "UPDATE " + table + " SET " + String.join(", ", sets) + " WHERE id = ? AND record_id = ?";
            java.util.Set<Long> had = new java.util.HashSet<>(jdbc.queryForList("SELECT id FROM " + table + " WHERE record_id = ?", Long.class, id)), kept = new java.util.HashSet<>();
            int number = 0;
            for (JsonNode line : data.path(set.name())) {
                number++;
                Long own = line.hasNonNull("_line") && line.get("_line").canConvertToLong() ? line.get("_line").asLong() : null;
                if (own != null && had.contains(own) && kept.add(own)) {
                    List<Object> args = new ArrayList<>(java.util.Arrays.asList(number));
                    for (AppDefinitions.Field field : set.fields()) args.add(given(field, line.get(field.name())));
                    args.add(own); args.add(id);
                    jdbc.update(change, args.toArray());
                } else {
                    List<Object> args = new ArrayList<>(java.util.Arrays.asList(id, number));
                    for (AppDefinitions.Field field : set.fields()) args.add(given(field, line.get(field.name())));
                    jdbc.update(insert, args.toArray());
                }
            }
            for (Long gone : had) if (!kept.contains(gone)) {
                String user = usedLine(definition.key(), set.name(), gone);
                if (user != null) throw new ResponseStatusException(HttpStatus.CONFLICT, set.label() + "에서 지운 줄을 " + user + " 이(가) 쓰고 있어 지울 수 없습니다. 그쪽에서 먼저 빼야 합니다.");
                jdbc.update("DELETE FROM " + table + " WHERE id = ?", gone);
            }
        }
    }

    /** Which screen points at this line (its title), or null: a line that something else uses may not go. */
    public String usedLine(String key, String set, long lineId) {
        for (AppDefinitions.Stored other : definitions.all()) {
            AppDefinitions.Definition user = other.definition();
            if (!keeps(user)) continue;
            List<AppDefinitions.Field> all = new ArrayList<>(user.fields());
            for (AppDefinitions.LineSet lines : user.lineSets()) all.addAll(lines.fields());
            for (AppDefinitions.Field field : all) {
                if (field.ref() == null || !field.ref().line() || !field.ref().entity().equals(key) || !"lines".equals(set)) continue;
                boolean inLines = !user.fields().contains(field);
                String sql = inLines ? "SELECT COUNT(*) FROM " + lineTable(user.key(), "lines") + " WHERE " + column(field.name()) + " = ?" : "SELECT COUNT(*) FROM " + table(user.key()) + " WHERE " + column(field.name()) + " = ?";
                if (exists(inLines ? lineTable(user.key(), "lines") : table(user.key()))) {
                    Long found = jdbc.queryForObject(sql, Long.class, lineId);
                    if (found != null && found > 0) return user.title();
                }
            }
        }
        return null;
    }
    /** The record a line belongs to (null when there is no such line). */
    public Long lineOwner(String key, long lineId) {
        if (!exists(lineTable(key, "lines"))) return null;
        List<Long> rows = jdbc.queryForList("SELECT record_id FROM " + lineTable(key, "lines") + " WHERE id = ?", Long.class, lineId);
        return rows.isEmpty() ? null : rows.get(0);
    }
    /** Lines of an entity (all, or of the records whose `field` holds `value`), each with its id, its record and the record's fields as _owner. */
    public List<Map<String, Object>> lineRows(AppDefinitions.Definition definition, String field, String value, java.util.Collection<Long> ids) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (definition.lines() == null) return recordRows(definition, field, value);
        if (!exists(lineTable(definition.key(), "lines"))) return out;
        List<Object> args = new ArrayList<>();
        String where = "TRUE";
        if (field != null && definition.field(field) != null && value != null && !value.isBlank()) where = equal(definition.field(field), "t", value, args);
        if (ids != null && !ids.isEmpty()) { where += " AND l.id = ANY(?)"; args.add(ids.toArray(new Long[0])); }
        tools.jackson.databind.ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
        jdbc.query("SELECT l.id, l.record_id, (" + pairs(definition.lines().fields(), "l") + ")::text AS line, (" + pairs(definition.fields(), "t") + ")::text AS owner FROM "
                + lineTable(definition.key(), "lines") + " l JOIN " + table(definition.key()) + " t ON t.id = l.record_id WHERE " + where + " ORDER BY t.id, l.line_no LIMIT 5000", row -> {
            Map<String, Object> one = new java.util.LinkedHashMap<>();
            one.put("id", row.getLong("id")); one.put("recordId", row.getLong("record_id"));
            one.putAll(mapper.readValue(row.getString("line"), new tools.jackson.core.type.TypeReference<java.util.LinkedHashMap<String, Object>>() {}));
            one.put("_owner", mapper.readValue(row.getString("owner"), new tools.jackson.core.type.TypeReference<java.util.LinkedHashMap<String, Object>>() {}));
            out.add(one);
        }, args.toArray());
        return out;
    }

    public void setStatus(String key, long id, String status, String user) {
        jdbc.update("UPDATE " + table(key) + " SET status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", status, user, id);
    }
    public void delete(String key, long id) { jdbc.update("DELETE FROM " + table(key) + " WHERE id = ?", id); }

    /**
     * A condition "this field is this value" on a column, with the value read as the column's kind. A value that cannot be of that
     * kind (letters asked of a number) matches nothing rather than failing. Returns the SQL; the argument is added to args.
     */
    public static String equal(AppDefinitions.Field field, String alias, String wanted, List<Object> args) {
        String column = alias + "." + column(field.name()), type = sqlType(field), value = wanted == null ? "" : wanted.trim();
        boolean fits = switch (field.type()) {
            case "number" -> value.matches("-?\\d{1,18}(\\.\\d{1,10})?");
            case "ref" -> value.matches("\\d{1,18}");
            case "date" -> value.matches("\\d{4}-\\d{2}-\\d{2}");
            case "time" -> value.matches("\\d{2}:\\d{2}(:\\d{2})?");
            default -> true;
        };
        if (!fits) return "FALSE";
        args.add(value);
        return type.equals("text") || type.equals("character varying") ? column + " = ?" : column + " = CAST(? AS " + type + ")";
    }

    /** How many records of a screen hold this value in a field above the lines. */
    public long countWhere(String key, String fieldName, String value, Long exceptId) {
        AppDefinitions.Stored stored = definitions.find(key);
        AppDefinitions.Field field = stored == null || !keeps(stored.definition()) ? null : stored.definition().field(fieldName);
        if (field == null || !exists(table(key))) return 0;
        List<Object> args = new ArrayList<>();
        String sql = "SELECT COUNT(*) FROM " + table(key) + " t WHERE " + equal(field, "t", value, args);
        if (exceptId != null) { sql += " AND t.id <> ?"; args.add(exceptId); }
        Long found = jdbc.queryForObject(sql, Long.class, args.toArray());
        return found == null ? 0 : found;
    }
    /** How many records of a screen have a line (of the named table of lines) holding this value in a field. */
    public long countLines(AppDefinitions.Definition definition, AppDefinitions.LineSet set, AppDefinitions.Field field, String value) {
        if (!exists(lineTable(definition.key(), set.name()))) return 0;
        List<Object> args = new ArrayList<>();
        Long found = jdbc.queryForObject("SELECT COUNT(DISTINCT l.record_id) FROM " + lineTable(definition.key(), set.name()) + " l WHERE " + equal(field, "l", value, args), Long.class, args.toArray());
        return found == null ? 0 : found;
    }
    /** How many records of a screen hold all these values together (one record left out by id). */
    public long countCombination(AppDefinitions.Definition definition, Map<String, JsonNode> values, Long exceptId) {
        if (!exists(table(definition.key()))) return 0;
        List<Object> args = new ArrayList<>();
        List<String> parts = new ArrayList<>();
        for (Map.Entry<String, JsonNode> entry : values.entrySet()) {
            AppDefinitions.Field field = definition.field(entry.getKey());
            if (entry.getValue() == null || entry.getValue().isNull()) parts.add("t." + column(field.name()) + " IS NULL");
            else parts.add(equal(field, "t", entry.getValue().isNumber() ? new BigDecimal(entry.getValue().asString()).stripTrailingZeros().toPlainString() : entry.getValue().asString(), args));
        }
        String sql = "SELECT COUNT(*) FROM " + table(definition.key()) + " t WHERE " + String.join(" AND ", parts);
        if (exceptId != null) { sql += " AND t.id <> ?"; args.add(exceptId); }
        Long found = jdbc.queryForObject(sql, Long.class, args.toArray());
        return found == null ? 0 : found;
    }
    /** How many records with the same `by` values have a period that meets [from, to] (to null = open), one record left out. */
    public long countOverlap(AppDefinitions.Definition definition, Map<String, JsonNode> by, String from, String to, Long exceptId) {
        AppDefinitions.Effective period = definition.effective();
        if (!exists(table(definition.key()))) return 0;
        List<Object> args = new ArrayList<>();
        List<String> parts = new ArrayList<>();
        for (Map.Entry<String, JsonNode> entry : by.entrySet()) {
            AppDefinitions.Field field = definition.field(entry.getKey());
            if (entry.getValue() == null || entry.getValue().isNull()) parts.add("t." + column(field.name()) + " IS NULL");
            else parts.add(equal(field, "t", entry.getValue().isNumber() ? new BigDecimal(entry.getValue().asString()).stripTrailingZeros().toPlainString() : entry.getValue().asString(), args));
        }
        String end = period.to() == null ? "'infinity'::date" : "COALESCE(t." + column(period.to()) + ", 'infinity'::date)";
        parts.add("t." + column(period.from()) + " <= COALESCE(CAST(? AS date), 'infinity'::date)"); args.add(to);
        parts.add(end + " >= CAST(? AS date)"); args.add(from);
        String sql = "SELECT COUNT(*) FROM " + table(definition.key()) + " t WHERE " + String.join(" AND ", parts);
        if (exceptId != null) { sql += " AND t.id <> ?"; args.add(exceptId); }
        Long found = jdbc.queryForObject(sql, Long.class, args.toArray());
        return found == null ? 0 : found;
    }

    /** A record of the same `by` whose span meets [from, to] (dates: whole days, so touching ends meet; times: half open), statuses in ignore
     *  left out, one record left out: its from and to, or null. */
    public Map<String, Object> spanMet(AppDefinitions.Definition definition, AppDefinitions.NoOverlap span, Map<String, JsonNode> by, String from, String to, Long exceptId) {
        if (!exists(table(definition.key()))) return null;
        boolean times = definition.field(span.from()).type().equals("time");
        String cast = times ? "time" : "date";
        List<Object> args = new ArrayList<>();
        List<String> parts = new ArrayList<>();
        for (Map.Entry<String, JsonNode> entry : by.entrySet()) {
            AppDefinitions.Field field = definition.field(entry.getKey());
            if (entry.getValue() == null || entry.getValue().isNull()) parts.add("t." + column(field.name()) + " IS NULL");
            else parts.add(equal(field, "t", entry.getValue().isNumber() ? new BigDecimal(entry.getValue().asString()).stripTrailingZeros().toPlainString() : entry.getValue().asString(), args));
        }
        String start = "t." + column(span.from()), end = "t." + column(span.to());
        parts.add(start + (times ? " < " : " <= ") + "CAST(? AS " + cast + ")"); args.add(to);
        parts.add(end + (times ? " > " : " >= ") + "CAST(? AS " + cast + ")"); args.add(from);
        if (!span.ignore().isEmpty()) { parts.add("(t.status IS NULL OR t.status NOT IN (" + String.join(", ", java.util.Collections.nCopies(span.ignore().size(), "?")) + "))"); args.addAll(span.ignore()); }
        String sql = "SELECT " + start + "::text AS span_from, " + end + "::text AS span_to FROM " + table(definition.key()) + " t WHERE " + String.join(" AND ", parts);
        if (exceptId != null) { sql += " AND t.id <> ?"; args.add(exceptId); }
        List<Map<String, Object>> found = jdbc.queryForList(sql + " LIMIT 1", args.toArray());
        return found.isEmpty() ? null : found.get(0);
    }

    /** The line values of `child` in the records whose `parent` is one of these (the parts of these items' BOMs), leaving one record out. */
    public List<Long> childrenOf(AppDefinitions.Definition definition, String parent, String child, java.util.Collection<Long> parents, Long exceptId) {
        if (parents.isEmpty() || !exists(table(definition.key()))) return List.of();
        if (definition.field(child) != null)          // one pair per record: the child is a field of the record itself
            return jdbc.queryForList("SELECT DISTINCT t." + column(child) + " FROM " + table(definition.key()) + " t WHERE t." + column(parent) + " = ANY(?) AND t." + column(child) + " IS NOT NULL AND t.id <> ?",
                    Long.class, parents.toArray(new Long[0]), exceptId == null ? -1L : exceptId);
        return jdbc.queryForList("SELECT DISTINCT l." + column(child) + " FROM " + table(definition.key()) + " t JOIN " + lineTable(definition.key(), "lines") + " l ON l.record_id = t.id WHERE t."
                + column(parent) + " = ANY(?) AND l." + column(child) + " IS NOT NULL AND t.id <> ?", Long.class, parents.toArray(new Long[0]), exceptId == null ? -1L : exceptId);
    }

    /** For a master without lines: its records whose `field` holds `value`, each standing as its own "line" (with itself as _owner). */
    private List<Map<String, Object>> recordRows(AppDefinitions.Definition definition, String field, String value) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (!exists(table(definition.key())) || field == null || definition.field(field) == null) return out;
        List<Object> args = new ArrayList<>();
        String where = equal(definition.field(field), "t", value, args);
        tools.jackson.databind.ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
        jdbc.query("SELECT t.id, (" + pairs(definition.fields(), "t") + ")::text AS data FROM " + table(definition.key()) + " t WHERE " + where + " ORDER BY t.id LIMIT 5000", row -> {
            Map<String, Object> one = new java.util.LinkedHashMap<>(mapper.readValue(row.getString("data"), new tools.jackson.core.type.TypeReference<java.util.LinkedHashMap<String, Object>>() {}));
            one.put("id", row.getLong("id")); one.put("recordId", row.getLong("id"));
            one.put("_owner", new java.util.LinkedHashMap<>(one));
            out.add(one);
        }, args.toArray());
        return out;
    }

    /** The highest value of a text field that starts with this (the last number given in a series). */
    public String highest(String key, String fieldName, String start) {
        return jdbc.queryForObject("SELECT MAX(" + column(fieldName) + ") FROM " + table(key) + " WHERE " + column(fieldName) + " LIKE ?", String.class, start + "%");
    }

    /**
     * A number field added up per group of key fields, by the database: for limits and for what an earlier stage leaves open.
     * lines: add up over the lines (a name found among the line fields is the line's, any other the record's); "id" among the keys is the
     * record's id. Returns rows of key parts (as text, "" for none) and their sum; records in the ignored statuses and one record by id are left out.
     */
    public List<Map.Entry<List<String>, Double>> sums(AppDefinitions.Definition definition, String fieldName, boolean lines, List<String> by, List<String> ignore, Long except) {
        List<Map.Entry<List<String>, Double>> out = new ArrayList<>();
        if (!exists(table(definition.key()))) return out;
        boolean joined = lines && definition.lines() != null;
        java.util.function.Function<String, String> at = name -> name.equals("id") ? "t.id"
                : (joined && definition.lines().fields().stream().anyMatch(field -> field.name().equals(name)) ? "l." : "t.") + column(name);
        java.util.function.Predicate<String> known = name -> name.equals("id") || definition.field(name) != null || (joined && definition.lines().fields().stream().anyMatch(field -> field.name().equals(name)));
        boolean once = fieldName == null || fieldName.isEmpty();          // a limit without quantities: each record (or line) counts one
        if (!once && !known.test(fieldName)) return out;
        List<String> parts = new ArrayList<>();
        for (String name : by) parts.add(known.test(name) ? "COALESCE(" + at.apply(name) + "::text, '')" : "''");
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder("SELECT " + (parts.isEmpty() ? "" : String.join(", ", parts) + ", ") + (once ? "COUNT(*)" : "SUM(" + at.apply(fieldName) + ")") + " AS total FROM " + table(definition.key()) + " t");
        if (joined) sql.append(" JOIN ").append(lineTable(definition.key(), "lines")).append(" l ON l.record_id = t.id");
        sql.append(" WHERE ").append(once ? "TRUE" : at.apply(fieldName) + " IS NOT NULL");
        if (except != null) { sql.append(" AND t.id <> ?"); args.add(except); }
        if (!ignore.isEmpty()) { sql.append(" AND (t.status IS NULL OR t.status NOT IN (").append(String.join(", ", java.util.Collections.nCopies(ignore.size(), "?"))).append("))"); args.addAll(ignore); }
        if (!parts.isEmpty()) { List<String> places = new ArrayList<>(); for (int index = 1; index <= parts.size(); index++) places.add(String.valueOf(index)); sql.append(" GROUP BY ").append(String.join(", ", places)); }
        jdbc.query(sql.toString(), row -> {
            List<String> keys = new ArrayList<>();
            for (int index = 1; index <= parts.size(); index++) keys.add(plain(row.getString(index)));
            out.add(Map.entry(keys, row.getDouble("total")));
        }, args.toArray());
        return out;
    }
    /** A number as the rules write it in a key: 10, not 10.0 or 10.00. */
    private static String plain(String text) {
        if (text == null) return "";
        return text.matches("-?\\d+\\.\\d*0+") || text.matches("-?\\d+\\.0*") ? new BigDecimal(text).stripTrailingZeros().toPlainString() : text;
    }

    /**
     * Bring every screen's tables up to its definition, and carry over the records an older version kept together in one table
     * (app_records, each record a JSON value): they go into their screen's table with the ids they had. Run at start, before anything else.
     */
    public void prepare() {
        boolean old = exists("app_records");
        for (AppDefinitions.Stored stored : definitions.all()) {
            AppDefinitions.Definition definition = stored.definition();
            if (!keeps(definition)) continue;
            try {
                ensure(definition);
                if (!old) continue;
                List<Map<String, Object>> rows = jdbc.queryForList("SELECT id, data::text AS data, status, created_by, created_at, updated_by, updated_at FROM app_records WHERE entity_key = ? ORDER BY id", definition.key());
                if (rows.isEmpty()) continue;
                tools.jackson.databind.ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
                int moved = 0;
                for (Map<String, Object> row : rows) {
                    long id = ((Number) row.get("id")).longValue();
                    if (has(definition.key(), id)) continue;
                    JsonNode data = readable(definition, mapper.readTree((String) row.get("data")), mapper);
                    insert(definition, data, (String) row.get("status"), (String) row.get("created_by"), id);
                    jdbc.update("UPDATE " + table(definition.key()) + " SET created_at = ?, updated_by = ?, updated_at = ? WHERE id = ?", row.get("created_at"), row.get("updated_by"), row.get("updated_at"), id);
                    moved++;
                }
                jdbc.update("DELETE FROM app_records WHERE entity_key = ?", definition.key());
                log.info("records of {} carried into {}: {}", definition.key(), table(definition.key()), moved);
            } catch (RuntimeException failed) {
                log.error("tables of screen {} could not be prepared: {}", definition.key(), failed.getMessage());
            }
        }
        // An older version kept every screen's history in one table (app_record_history): each screen's rows go into its own history table.
        if (exists("app_record_history")) {
            boolean all = true;
            for (AppDefinitions.Stored stored : definitions.all()) {
                AppDefinitions.Definition definition = stored.definition();
                if (!keeps(definition)) continue;
                try {
                    Integer already = jdbc.queryForObject("SELECT COUNT(*) FROM " + historyTable(definition.key()), Integer.class);
                    if (already != null && already > 0) continue;
                    int moved = 0;
                    for (Map<String, Object> row : jdbc.queryForList("SELECT record_id, action, action_name, automatic, COALESCE(after_data, before_data)::text AS record, status_before, status_after, "
                            + "changed_by, changed_at FROM app_record_history WHERE entity_key = ? ORDER BY history_id", definition.key())) {
                        noteHistory(definition, ((Number) row.get("record_id")).longValue(), (String) row.get("action"), (String) row.get("action_name"), Boolean.TRUE.equals(row.get("automatic")),
                                (String) row.get("record"), (String) row.get("status_before"), (String) row.get("status_after"), (String) row.get("changed_by"), (java.sql.Timestamp) row.get("changed_at"));
                        moved++;
                    }
                    if (moved > 0) log.info("history of {} carried into {}: {}", definition.key(), historyTable(definition.key()), moved);
                } catch (RuntimeException failed) {
                    all = false;
                    log.error("history of screen {} could not be carried over: {}", definition.key(), failed.getMessage());
                }
            }
            if (all) jdbc.execute("DROP TABLE app_record_history");
        }
    }
    /** A stored value that is not of its field's kind any more (the field changed kind long ago) is left empty rather than stopping the move. */
    private static JsonNode readable(AppDefinitions.Definition definition, JsonNode data, tools.jackson.databind.ObjectMapper mapper) {
        tools.jackson.databind.node.ObjectNode out = (tools.jackson.databind.node.ObjectNode) data.deepCopy();
        java.util.function.BiConsumer<List<AppDefinitions.Field>, tools.jackson.databind.node.ObjectNode> tidy = (fields, unit) -> {
            for (AppDefinitions.Field field : fields) {
                JsonNode value = unit.get(field.name());
                if (value == null || value.isNull()) continue;
                String text = value.asString().trim();
                boolean fits = switch (field.type()) {
                    case "number" -> value.isNumber() || text.matches("-?\\d{1,18}(\\.\\d{1,10})?");
                    case "ref" -> value.isIntegralNumber() || text.matches("\\d{1,18}");
                    case "date" -> text.matches("\\d{4}-\\d{2}-\\d{2}");
                    case "time" -> text.matches("\\d{2}:\\d{2}(:\\d{2})?");
                    default -> true;
                };
                if (!fits) unit.putNull(field.name());
            }
        };
        tidy.accept(definition.fields(), out);
        for (AppDefinitions.LineSet set : definition.lineSets())
            for (JsonNode line : out.path(set.name())) if (line.isObject()) tidy.accept(set.fields(), (tools.jackson.databind.node.ObjectNode) line);
        return out;
    }
}
