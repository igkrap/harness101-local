package com.example.localinventory.framework.app;

import com.example.localinventory.framework.system.SystemAccessService;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Rows of any defined entity: one API for all of them, behaving as the definition says.
 * Program permissions apply through the path (/api/data/{entity} belongs to the entity's program).
 */
@RestController
@RequestMapping("/api/data/{entity}")
public class RecordController {
    private static final String COLUMNS = "id, data::text AS data, status, created_by, created_at, updated_by, updated_at";
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    private final SystemAccessService access;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    private final RecordHistory history;
    private final RecordStore store;
    private final QuantityLedger quantities;
    private final PeriodLocks locks;
    public RecordController(AppDefinitions definitions, JdbcTemplate jdbc, SystemAccessService access, RecordHistory history, RecordStore store, QuantityLedger quantities, PeriodLocks locks) { this.locks = locks;
        this.definitions = definitions; this.jdbc = jdbc; this.access = access; this.history = history; this.store = store; this.quantities = quantities;
    }

    /** One page of a list and how many records the conditions match in all. */
    public record Page(List<Map<String, Object>> rows, long total) {}

    /**
     * Query parameters named like header fields filter the list (text contains, other types equal); status filters by status code.
     * Parameters that start with an underscore shape the answer: _limit (2,000 unless given, at most 100,000), _offset,
     * _sort (a header field's name, id, status or updatedAt) and _desc=true. The X-Total-Count header tells how many match in all.
     * Each row carries _names: what its fields that point at other screens' records read as ("V-001 한빛상사").
     */
    @GetMapping
    public List<Map<String, Object>> list(@PathVariable String entity, @RequestParam Map<String, String> filters, Authentication authentication,
                                          jakarta.servlet.http.HttpServletResponse response) {
        Page page = page(definition(entity, authentication), filters, List.of());
        if (response != null) response.setHeader("X-Total-Count", String.valueOf(page.total()));
        return page.rows();
    }

    /** statuses: only records in one of these (a work screen's list); empty = any. */
    Page page(AppDefinitions.Definition definition, Map<String, String> filters, List<String> statuses) {
        StringBuilder where = new StringBuilder(" FROM " + RecordStore.table(definition.key()) + " t WHERE TRUE");
        List<Object> args = new ArrayList<>();
        if (!statuses.isEmpty()) {
            where.append(" AND t.status IN (").append(String.join(", ", java.util.Collections.nCopies(statuses.size(), "?"))).append(")");
            args.addAll(statuses);
        }
        for (Map.Entry<String, String> filter : filters.entrySet()) {
            if (filter.getValue() == null || filter.getValue().isBlank() || filter.getKey().startsWith("_")) continue;
            if (filter.getKey().equals("status")) { where.append(" AND t.status = ?"); args.add(filter.getValue().trim()); continue; }
            String name = filter.getKey(), wanted = filter.getValue().trim();
            // A period of a date field: <field>_from and <field>_to (both ends included).
            if (name.endsWith("_from") || name.endsWith("_to")) {
                boolean from = name.endsWith("_from");
                AppDefinitions.Field date = definition.field(name.substring(0, name.length() - (from ? 5 : 3)));
                if (date != null && date.type().equals("date")) {
                    if (!wanted.matches("\\d{4}-\\d{2}-\\d{2}")) { where.append(" AND FALSE"); continue; }
                    where.append(" AND t.").append(RecordStore.column(date.name())).append(from ? " >= CAST(? AS date)" : " <= CAST(? AS date)"); args.add(wanted); continue;
                }
            }
            // A field of the lines: lines.<field> finds the records that have such a line (the orders an item is on).
            // (a further table of lines by its own name: materials.<field>)
            if (name.contains(".")) {
                String table = name.substring(0, name.indexOf('.')), inner = name.substring(name.indexOf('.') + 1);
                for (AppDefinitions.LineSet set : definition.lineSets())
                    for (AppDefinitions.Field candidate : set.fields())
                        if (set.name().equals(table) && candidate.name().equals(inner))
                            where.append(" AND EXISTS (SELECT 1 FROM ").append(RecordStore.lineTable(definition.key(), set.name())).append(" l WHERE l.record_id = t.id AND ").append(RecordStore.equal(candidate, "l", wanted, args)).append(")");
                continue;
            }
            AppDefinitions.Field field = definition.field(filter.getKey());
            if (field == null) continue;
            String column = "t." + RecordStore.column(field.name());
            if (field.type().equals("yesno")) where.append(yes(filter.getValue()) ? " AND " + column + " IS TRUE" : " AND " + column + " IS NOT TRUE");
            else if (field.wordy()) { where.append(" AND LOWER(").append(column).append(") LIKE ?"); args.add("%" + filter.getValue().trim().toLowerCase() + "%"); }
            else where.append(" AND ").append(RecordStore.equal(field, "t", wanted, args));
        }
        Long total = jdbc.queryForObject("SELECT COUNT(*)" + where, Long.class, args.toArray());
        boolean descending = "true".equalsIgnoreCase(filters.get("_desc"));
        String sort = filters.getOrDefault("_sort", "id"), direction = descending ? " DESC NULLS LAST" : " ASC NULLS LAST", order;
        AppDefinitions.Field by = definition.field(sort);
        if (by != null) order = "t." + RecordStore.column(by.name()) + direction + ", t.id";       // a column of its own kind: numbers in order as numbers, dates as dates
        else order = (sort.equals("status") ? "t.status" : sort.equals("updatedAt") ? "t.updated_at" : "t.id") + direction + (sort.equals("id") ? "" : ", t.id");
        int limit = Math.max(1, Math.min(100000, number(filters.get("_limit"), 2000))), offset = Math.max(0, number(filters.get("_offset"), 0));
        List<Map<String, Object>> rows = jdbc.query("SELECT " + RecordStore.select(definition) + where + " ORDER BY " + order + " LIMIT " + limit + " OFFSET " + offset,
                (row, index) -> view(definition, row.getLong("id"), row.getString("data"), row.getString("status"), row.getString("created_by"),
                row.getTimestamp("created_at"), row.getString("updated_by"), row.getTimestamp("updated_at")), args.toArray());
        named(definition, rows);
        return new Page(rows, total == null ? rows.size() : total);
    }

    private static int number(String text, int otherwise) {
        try { return text == null || text.isBlank() ? otherwise : Integer.parseInt(text.trim()); } catch (NumberFormatException error) { return otherwise; }
    }

    /** Give each row _names: how its header fields that point at other records read (code and name), looked up once per field for the whole page. */
    private void named(AppDefinitions.Definition definition, List<Map<String, Object>> rows) { named(definition.fields(), rows); }
    void named(List<AppDefinitions.Field> fields, List<Map<String, Object>> rows) {
        for (Map<String, Object> row : rows) row.put("_names", new LinkedHashMap<String, String>());
        for (AppDefinitions.Field field : fields) {
            if (field.ref() == null) continue;
            java.util.Set<Long> ids = new java.util.LinkedHashSet<>();
            for (Map<String, Object> row : rows) if (row.get(field.name()) instanceof Number id) ids.add(id.longValue());
            if (ids.isEmpty()) continue;
            if (field.ref().line()) {        // a line of another master reads as that line's label
                AppDefinitions.Stored target = definitions.find(field.ref().entity());
                Map<Long, String> shown = new LinkedHashMap<>();
                if (target != null) for (Map<String, Object> line : store.lineRows(target.definition(), null, null, ids)) shown.put(((Number) line.get("id")).longValue(), String.valueOf(line.getOrDefault(field.ref().label(), "")));
                for (Map<String, Object> row : rows)
                    if (row.get(field.name()) instanceof Number id && shown.containsKey(id.longValue())) {
                        @SuppressWarnings("unchecked") Map<String, String> into = (Map<String, String>) row.get("_names");
                        into.put(field.name(), shown.get(id.longValue()));
                    }
                continue;
            }
            String code = definitions.codeField(field.ref());
            Map<Long, String> names = new LinkedHashMap<>();
            jdbc.query("SELECT id, data->>? AS name, data->>? AS code FROM " + store.source(field.ref().entity()) + " app_records WHERE entity_key = ? AND id = ANY(?)", row -> {
                String shown = ((row.getString("code") == null || code == null ? "" : row.getString("code") + " ") + (row.getString("name") == null ? "" : row.getString("name"))).trim();
                names.put(row.getLong("id"), shown);
            }, field.ref().label(), code == null ? "" : code, field.ref().entity(), ids.toArray(new Long[0]));
            for (Map<String, Object> row : rows)
                if (row.get(field.name()) instanceof Number id && names.containsKey(id.longValue())) {
                    @SuppressWarnings("unchecked") Map<String, String> into = (Map<String, String>) row.get("_names");
                    into.put(field.name(), names.get(id.longValue()));
                }
        }
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String entity, @PathVariable long id, Authentication authentication) {
        return one(definition(entity, authentication), id);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    @Transactional
    public Map<String, Object> create(@PathVariable String entity, @RequestBody JsonNode body, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        ownScreen(definition, authentication);
        return one(definition, insert(definition, body, authentication.getName(), 0));
    }
    /** A later stage registers nothing on its own screen: its records come from the stage before (a take-over screen) or from a 기타 screen.
     *  Administrators still may (fixing data, carrying it over, the platform's checks) - as with deleting by force. */
    /** The date a record is locked by (its lock's date field), as it stands or as it is about to be stored. */
    private static Object lockDay(AppDefinitions.Definition definition, Map<String, Object> record) {
        return definition.lock() == null || record == null ? null : record.get(definition.lock().date());
    }
    private static Object lockDay(AppDefinitions.Definition definition, ObjectNode data) {
        return definition.lock() == null || data == null || !data.hasNonNull(definition.lock().date()) ? null : data.get(definition.lock().date()).asString();
    }
    /** Data only: made and moved on by what happens elsewhere; nobody changes it directly (administrators may, to put data right). */
    private void dataOnly(AppDefinitions.Definition definition, Authentication authentication) {
        if (!definition.dataOnly() || access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList())) return;
        throw new ResponseStatusException(HttpStatus.FORBIDDEN, plainName(definition) + " 은(는) 다른 업무에서 저절로 만들어지고 바뀌는 자료라 직접 등록하거나 고칠 수 없습니다.");
    }
    private void ownScreen(AppDefinitions.Definition definition, Authentication authentication) {
        dataOnly(definition, authentication);
        if (definition.follows() == null) return;
        if (access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList())) return;
        String earlier = earlierName(definition), taking = screensOf(definition, false), other = screensOf(definition, true);
        throw new ResponseStatusException(HttpStatus.CONFLICT, plainName(definition) + " 은(는) " + earlier + " 에서 이어서 등록합니다" + (taking.isEmpty() ? "." : ": " + taking + ".")
                + (other.isEmpty() ? "" : " " + earlier + " 없이 등록하려면 " + other + " 에서 합니다."));
    }
    private static String plainName(AppDefinitions.Definition definition) { return definition.title().replaceAll("\\s*(등록|관리|입력)$", ""); }
    private String earlierName(AppDefinitions.Definition definition) {
        AppDefinitions.Field pointer = definition.field(definition.follows());
        return pointer == null || pointer.ref() == null ? "앞 단계" : java.util.Optional.ofNullable(definitions.find(pointer.ref().entity())).map(stored -> plainName(stored.definition())).orElse("앞 단계");
    }
    /** The screens people register this entity on: the take-over screens from the stage before, or (other) the screens that register it without one. */
    private String screensOf(AppDefinitions.Definition definition, boolean other) {
        List<String> names = new ArrayList<>();
        for (AppDefinitions.Stored stored : definitions.all()) {
            AppDefinitions.Definition screen = stored.definition();
            if (!stored.status().equals("PUBLISHED") || screen.key().startsWith("trial_")) continue;
            if (!other && screen.take() != null && screen.take().entity().equals(definition.key())) names.add("「" + screen.title() + "」");
            if (other && screen.over() != null && screen.over().create() && screen.over().entity().equals(definition.key())) names.add("「" + screen.title() + "」");
        }
        return String.join(", ", names);
    }
    /** From a take-over screen (the stage before is given), or from a 기타 screen (it must not be: that is what 기타 is for). */
    @Transactional
    public Map<String, Object> createFrom(String entity, JsonNode body, Authentication authentication, boolean other) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        if (other && definition.follows() != null && body.hasNonNull(definition.follows()) && !body.get(definition.follows()).asString().isBlank())
            throw bad("이 화면에서는 " + earlierName(definition) + " 을(를) 고르지 않습니다 (" + definition.field(definition.follows()).label() + " 은(는) 비워 둡니다)."
                    + (screensOf(definition, false).isEmpty() ? "" : " " + earlierName(definition) + " 이(가) 있으면 " + screensOf(definition, false) + " 에서 등록합니다."));
        return one(definition, insert(definition, body, authentication.getName(), 0));
    }

    public record ImportRequest(List<Map<String, Object>> rows) {}

    /**
     * Many records at once (a sheet pasted or uploaded). Each row is keyed by field name or by the label on screen, and its values may be
     * written as people see them: a record of another screen by its code, its name or "code name"; a common code by its name; numbers
     * with separators; dates as 2026-01-15, 2026/01/15, 2026.01.15 or 20260115. Every row goes through the same rules as typing it in.
     * All or nothing: when any row is refused, nothing is stored and every refusal comes back with its row number.
     */
    @PostMapping("/import")
    @Transactional
    public Map<String, Object> importRows(@PathVariable String entity, @RequestBody ImportRequest request, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        ownScreen(definition, authentication);
        List<Map<String, Object>> rows = request == null || request.rows() == null ? List.of() : request.rows();
        if (rows.isEmpty() || rows.size() > 5000) throw bad("올릴 줄은 1~5000개여야 합니다.");
        Map<String, Map<String, Long>> targets = new LinkedHashMap<>();
        Map<String, Map<String, String>> codes = new LinkedHashMap<>();
        List<Map<String, Object>> problems = new ArrayList<>();
        // With a lines table, each sheet row is one line; rows that follow each other with the same values above the lines are one record.
        List<AppDefinitions.Field> lineFields = definition.lines() == null ? List.of() : definition.lines().fields();
        java.util.Set<String> headerLabels = new java.util.HashSet<>();
        for (AppDefinitions.Field field : definition.fields()) headerLabels.add(field.label());
        int number = 0, stored = 0, first = 0;
        ObjectNode body = null;
        String open = null;
        for (int index = 0; index <= rows.size(); index++) {
            Map<String, Object> row = index < rows.size() ? rows.get(index) : null;
            String key = null;
            try {
                if (row != null) {
                    number = index + 1;
                    ObjectNode head = mapper.createObjectNode();
                    for (AppDefinitions.Field field : definition.fields()) {
                        if (field.computed()) continue;
                        String text = given(row, field.name(), field.label());
                        if (!text.isEmpty()) put(head, field, text, targets, codes, "");
                    }
                    key = lineFields.isEmpty() ? null : head.toString();
                    if (body != null && (key == null || !key.equals(open))) { int at = first; ObjectNode done = body; body = null; number = at; insert(definition, done, authentication.getName(), 0); stored++; number = index + 1; }
                    if (body == null) { body = head; open = key; first = index + 1; if (!lineFields.isEmpty()) body.set("lines", mapper.createArrayNode()); }
                    if (!lineFields.isEmpty()) {
                        ObjectNode line = mapper.createObjectNode();
                        for (AppDefinitions.Field field : lineFields) {
                            if (field.formula() != null) continue;
                            String label = headerLabels.contains(field.label()) ? definition.lines().label() + " " + field.label() : field.label();
                            String text = given(row, "lines." + field.name(), label);
                            if (!text.isEmpty()) put(line, field, text, targets, codes, "lines.");
                        }
                        if (!line.isEmpty()) ((ArrayNode) body.get("lines")).add(line);
                    }
                } else if (body != null) { number = first; ObjectNode done = body; body = null; insert(definition, done, authentication.getName(), 0); stored++; }
            } catch (ResponseStatusException refused) {
                body = null; open = null;
                problems.add(Map.of("row", number, "message", refused.getReason() == null ? "저장할 수 없는 줄입니다." : refused.getReason()));
                // the row that could not be read does not start a record; the next row starts afresh
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        if (!problems.isEmpty()) org.springframework.transaction.interceptor.TransactionAspectSupport.currentTransactionStatus().setRollbackOnly();
        out.put("stored", problems.isEmpty() ? stored : 0);
        out.put("rows", rows.size());
        out.put("problems", problems);
        return out;
    }

    private static String given(Map<String, Object> row, String name, String label) {
        Object value = row.containsKey(name) ? row.get(name) : row.get(label);
        return value == null ? "" : String.valueOf(value).trim();
    }
    private void put(ObjectNode into, AppDefinitions.Field field, String text, Map<String, Map<String, Long>> targets, Map<String, Map<String, String>> codes, String scope) {
        switch (field.type()) {
            case "number" -> into.put(field.name(), text.replace(",", "").replace(" ", ""));
            case "date" -> into.put(field.name(), date(text, field.label()));
            case "yesno" -> into.put(field.name(), yes(text));
            case "ref" -> into.put(field.name(), pointed(field, text, targets, scope));
            case "code" -> into.put(field.name(), coded(field, text, codes));
            default -> into.put(field.name(), text);
        }
    }

    /** A yes as people and sheets write it: 예, Y, yes, true, 1, O, 사용 ... - anything else (and nothing) is a no. */
    static boolean yes(String text) { return text != null && java.util.Set.of("예", "네", "y", "yes", "true", "t", "1", "o", "v", "✓", "√", "사용", "완료").contains(text.trim().toLowerCase()); }
    /** A time as typed (0930, 9:30, 09:30:15, 093015) in the stored form 09:30:00; null when it is not a time. */
    static String time(String text) {
        String raw = text.trim();
        java.util.regex.Matcher parts = java.util.regex.Pattern.compile("(\\d{1,2}):(\\d{1,2})(?::(\\d{1,2}))?").matcher(raw);
        java.util.regex.Matcher packed = java.util.regex.Pattern.compile("(\\d{2})(\\d{2})(\\d{2})?").matcher(raw);
        java.util.regex.Matcher found = parts.matches() ? parts : packed.matches() ? packed : null;
        if (found == null) return null;
        int hour = Integer.parseInt(found.group(1)), minute = Integer.parseInt(found.group(2)), second = found.group(3) == null ? 0 : Integer.parseInt(found.group(3));
        return hour > 23 || minute > 59 || second > 59 ? null : String.format("%02d:%02d:%02d", hour, minute, second);
    }

    private static String date(String text, String label) {
        String digits = text.replaceAll("[./]", "-").replaceAll("\\s", "");
        if (digits.matches("\\d{8}")) digits = digits.substring(0, 4) + "-" + digits.substring(4, 6) + "-" + digits.substring(6);
        if (digits.matches("\\d{4}-\\d{1,2}-\\d{1,2}")) { String[] part = digits.split("-"); digits = part[0] + "-" + (part[1].length() == 1 ? "0" : "") + part[1] + "-" + (part[2].length() == 1 ? "0" : "") + part[2]; }
        try { return java.time.LocalDate.parse(digits).toString(); }
        catch (java.time.format.DateTimeParseException error) { throw bad(label + ": 날짜로 읽을 수 없습니다 (" + text + "). 2026/01/15 처럼 적습니다."); }
    }

    /** The record a sheet cell names: by its code, by its name, or by both together as the screens show it. */
    private long pointed(AppDefinitions.Field field, String text, Map<String, Map<String, Long>> targets, String scope) {
        Map<String, Long> known = targets.computeIfAbsent(scope + field.name(), ignored -> {
            Map<String, Long> out = new LinkedHashMap<>();
            String code = definitions.codeField(field.ref());
            for (Map<String, Object> row : jdbc.queryForList("SELECT id, data::text AS data FROM " + store.source(field.ref().entity()) + " app_records WHERE entity_key = ?", field.ref().entity())) {
                JsonNode data = mapper.readTree((String) row.get("data"));
                long id = ((Number) row.get("id")).longValue();
                String name = data.hasNonNull(field.ref().label()) ? data.get(field.ref().label()).asString() : "", tag = code != null && data.hasNonNull(code) ? data.get(code).asString() : "";
                for (String key : List.of(tag, name, (tag + " " + name).trim()))
                    if (!key.isEmpty()) out.merge(key, id, (first, second) -> first.equals(second) ? first : -1L);     // -1: more than one record answers to this
            }
            return out;
        });
        Long id = known.get(text);
        if (id == null) throw bad(field.label() + ": '" + text + "' 에 해당하는 자료가 없습니다. 코드나 이름을 등록된 그대로 적습니다.");
        if (id < 0) throw bad(field.label() + ": '" + text + "' 인 자료가 둘 이상입니다. 코드로 적습니다.");
        return id;
    }

    private String coded(AppDefinitions.Field field, String text, Map<String, Map<String, String>> codes) {
        Map<String, String> known = codes.computeIfAbsent(field.codeGroup(), ignored -> {
            Map<String, String> out = new LinkedHashMap<>();
            for (Map<String, Object> row : jdbc.queryForList("SELECT code, code_name FROM sys_codes WHERE group_code = ?", field.codeGroup())) {
                out.put((String) row.get("code"), (String) row.get("code"));
                out.putIfAbsent((String) row.get("code_name"), (String) row.get("code"));
            }
            return out;
        });
        String code = known.get(text);
        if (code == null) throw bad(field.label() + ": '" + text + "' 은(는) 고를 수 있는 값이 아닙니다 (" + String.join(", ", known.keySet()) + ").");
        return code;
    }

    /** Spans that may not overlap (noOverlap), judged once the record holds everything it will be stored with (who registered it too). */
    private void spans(AppDefinitions.Definition definition, ObjectNode out, Map<String, Object> current) {
        Long self = current == null ? null : ((Number) current.get("id")).longValue();
        String standing = current != null && current.get("status") != null ? String.valueOf(current.get("status")) : definition.status() == null ? null : definition.status().initial();
        for (AppDefinitions.NoOverlap span : definition.noOverlap()) {          // spans of the same kind (a room on a day) may not meet
            if (standing != null && span.ignore().contains(standing)) continue;
            if (!out.hasNonNull(span.from()) || !out.hasNonNull(span.to())) continue;
            String from = out.get(span.from()).asString(), to = out.get(span.to()).asString();
            AppDefinitions.Field start = definition.field(span.from()), end = definition.field(span.to());
            if (to.compareTo(from) < (start.type().equals("time") ? 1 : 0)) continue;     // the wrong way round: refused after the screen's own comparisons
            Map<String, JsonNode> by = new LinkedHashMap<>();
            for (String name : span.by()) by.put(name, out.get(name));
            Map<String, Object> other = store.spanMet(definition, span, by, from, to, self);
            if (other != null) {
                String said = span.by().stream().map(name -> definition.field(name).label()).collect(java.util.stream.Collectors.joining("·"));
                throw bad(span.message() != null ? span.message() + " (" + other.get("span_from") + " ~ " + other.get("span_to") + " 과 겹칩니다)"
                        : (said.isEmpty() ? "" : said + " 이(가) 같은 ") + start.label() + "~" + end.label() + " 이(가) 이미 있는 " + other.get("span_from") + " ~ " + other.get("span_to") + " 과 겹칩니다.");
            }
        }
    }

    /** Store a new record with every rule applied, then let what follows from it happen (also used for records an effect makes). */
    private long insert(AppDefinitions.Definition definition, JsonNode body, String user, int depth) {
        ObjectNode data = validated(definition, looked(definition, body), null);
        locks.open(definition, lockDay(definition, data), "등록");
        String status = definition.status() == null ? null : definition.status().initial();
        limits(definition, data, null, status);
        for (AppDefinitions.Field field : definition.fields())
            if (field.type().equals("serial")) data.put(field.name(), nextSerial(definition.key(), field));
            else if (field.type().equals("user")) data.put(field.name(), user);        // who registered it: the signed-in account, never typed
        spans(definition, data, null);
        Long id = store.insert(definition, data, status, user, null);
        quantities.post(definition, id, data, user);
        history.note(definition.key(), id, "CREATE", null, depth > 0, null, data.toString(), null, status, user);
        effects(definition, id, "create", user, depth);
        return id;
    }

    @PutMapping("/{id}")
    @Transactional
    public Map<String, Object> update(@PathVariable String entity, @PathVariable long id, @RequestBody JsonNode body, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        dataOnly(definition, authentication);
        Map<String, Object> current = one(definition, id);
        unchanged(current, "수정");
        guard(definition, id, (String) current.get("status"), "update", "수정");
        ObjectNode data = validated(definition, looked(definition, body), current);
        spans(definition, data, current);
        locks.open(definition, lockDay(definition, current), "수정");
        locks.open(definition, lockDay(definition, data), "수정");             // nor is a record moved into a locked month
        limits(definition, data, id, (String) current.get("status"));
        String before = history.stored(entity, id);
        quantities.reverse(definition, id);
        store.update(definition, id, data, authentication.getName());
        quantities.post(definition, id, data, authentication.getName());
        history.note(entity, id, "UPDATE", null, false, before, history.stored(entity, id), (String) current.get("status"), (String) current.get("status"), authentication.getName());
        return one(definition, id);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Transactional
    public void delete(@PathVariable String entity, @PathVariable long id, @RequestParam(defaultValue = "false") boolean force, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        dataOnly(definition, authentication);
        Map<String, Object> current = one(definition, id);
        // force (administrators only): a record in a locked status or held by a rule can still be removed - for cleaning up, not for daily work.
        // What other records point at stays protected either way.
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        if (force && !admin) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "관리자만 강제로 삭제할 수 있습니다.");
        unchanged(current, "삭제");
        if (!force) guard(definition, id, (String) current.get("status"), "delete", "삭제");
        // Built-in rule: a row that other rows point to (from a header or a line) cannot be deleted.
        for (AppDefinitions.Stored other : definitions.all()) {
            AppDefinitions.Definition user = other.definition();
            for (AppDefinitions.Field field : user.fields())
                if (field.ref() != null && field.ref().entity().equals(entity) && count(user.key(), field.name(), id) > 0)
                    throw new ResponseStatusException(HttpStatus.CONFLICT, user.title() + " " + count(user.key(), field.name(), id) + "건이 이 자료를 사용하고 있어 삭제할 수 없습니다.");
            for (AppDefinitions.LineSet set : user.lineSets())
                for (AppDefinitions.Field field : set.fields())
                    if (field.ref() != null && field.ref().entity().equals(entity)) {
                        Long users = store.countLines(user, set, field, String.valueOf(id));
                        if (users != null && users > 0)
                            throw new ResponseStatusException(HttpStatus.CONFLICT, user.title() + " " + users + "건의 " + set.label() + "에서 이 자료를 사용하고 있어 삭제할 수 없습니다.");
                    }
        }
        history.note(entity, id, "DELETE", null, false, history.stored(entity, id), null, (String) current.get("status"), null, authentication.getName());
        if (definition.lines() != null)          // a line another master points at (a step of this routing, a part of this BOM) holds the record
            for (Long line : jdbc.queryForList("SELECT id FROM " + RecordStore.lineTable(entity, "lines") + " WHERE record_id = ?", Long.class, id)) {
                String user = store.usedLine(entity, "lines", line);
                if (user != null) throw new ResponseStatusException(HttpStatus.CONFLICT, user + " 이(가) 이 자료의 줄을 쓰고 있어 삭제할 수 없습니다.");
            }
        locks.open(definition, lockDay(definition, current), "삭제");
        quantities.reverse(definition, id);
        quantities.named(entity, id);
        store.delete(entity, id);
        jdbc.update("DELETE FROM app_record_files WHERE entity_key = ? AND record_id = ?", entity, id);
    }

    private static final int FILE_LIMIT = 20 * 1024 * 1024, FILES_PER_RECORD = 30;

    /** Files attached to the record: id, name, size, who added it and when (the contents come one by one). */
    @GetMapping("/{id}/files")
    public List<Map<String, Object>> files(@PathVariable String entity, @PathVariable long id, Authentication authentication) {
        one(definition(entity, authentication), id);
        return jdbc.query("SELECT file_id, file_name, content_type, size_bytes, created_by, created_at FROM app_record_files WHERE entity_key = ? AND record_id = ? ORDER BY file_id", (row, index) -> {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("id", row.getLong("file_id")); out.put("name", row.getString("file_name")); out.put("type", row.getString("content_type"));
            out.put("size", row.getLong("size_bytes")); out.put("by", row.getString("created_by")); out.put("at", row.getTimestamp("created_at").toLocalDateTime().toString());
            return out;
        }, entity, id);
    }

    /** Attach a file: its bytes are the request body, its name the name parameter. Refused where the record itself may not be changed. */
    @PostMapping("/{id}/files")
    @ResponseStatus(HttpStatus.CREATED)
    @Transactional
    public Map<String, Object> attach(@PathVariable String entity, @PathVariable long id, @RequestParam String name, @RequestBody(required = false) byte[] content,
                                      @org.springframework.web.bind.annotation.RequestHeader(value = "Content-Type", required = false) String type, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        Map<String, Object> current = one(definition, id);
        guard(definition, id, (String) current.get("status"), "update", "수정");
        String clean = name == null ? "" : name.replaceAll("[\\\\/\\p{Cntrl}]", "_").trim();
        if (clean.isEmpty() || clean.length() > 255) throw bad("파일 이름이 없거나 너무 깁니다.");
        if (content == null || content.length == 0) throw bad("빈 파일은 붙일 수 없습니다.");
        if (content.length > FILE_LIMIT) throw bad("파일 하나는 20MB 까지 붙일 수 있습니다.");
        Integer held = jdbc.queryForObject("SELECT COUNT(*) FROM app_record_files WHERE entity_key = ? AND record_id = ?", Integer.class, entity, id);
        if (held != null && held >= FILES_PER_RECORD) throw bad("한 건에 파일은 " + FILES_PER_RECORD + "개까지 붙일 수 있습니다.");
        String kind = type == null || type.isBlank() || type.length() > 150 ? "application/octet-stream" : type;
        Long file = jdbc.queryForObject("INSERT INTO app_record_files (entity_key, record_id, file_name, content_type, size_bytes, content, created_by) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
                Long.class, entity, id, clean, kind, (long) content.length, content, authentication.getName());
        history.note(entity, id, "FILE_ADD", clean, false, null, null, null, null, authentication.getName());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", file); out.put("name", clean); out.put("size", content.length);
        return out;
    }

    /** The file itself, always as a download (never shown in place, whatever it claims to be). */
    @GetMapping("/{id}/files/{file}")
    public org.springframework.http.ResponseEntity<byte[]> file(@PathVariable String entity, @PathVariable long id, @PathVariable long file, Authentication authentication) {
        one(definition(entity, authentication), id);
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT file_name, content FROM app_record_files WHERE file_id = ? AND entity_key = ? AND record_id = ?", file, entity, id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "파일을 찾지 못했습니다.");
        String name = java.net.URLEncoder.encode((String) rows.get(0).get("file_name"), java.nio.charset.StandardCharsets.UTF_8).replace("+", "%20");
        return org.springframework.http.ResponseEntity.ok()
                .header("Content-Disposition", "attachment; filename*=UTF-8''" + name)
                .header("X-Content-Type-Options", "nosniff")
                .contentType(org.springframework.http.MediaType.APPLICATION_OCTET_STREAM)
                .body((byte[]) rows.get(0).get("content"));
    }

    @DeleteMapping("/{id}/files/{file}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @Transactional
    public void detach(@PathVariable String entity, @PathVariable long id, @PathVariable long file, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        Map<String, Object> current = one(definition, id);
        guard(definition, id, (String) current.get("status"), "update", "수정");
        List<String> names = jdbc.queryForList("SELECT file_name FROM app_record_files WHERE file_id = ? AND entity_key = ? AND record_id = ?", String.class, file, entity, id);
        if (names.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "파일을 찾지 못했습니다.");
        jdbc.update("DELETE FROM app_record_files WHERE file_id = ?", file);
        history.note(entity, id, "FILE_REMOVE", names.get(0), false, null, null, null, null, authentication.getName());
    }

    /**
     * What this record is tied to, both ways: the records of other screens that point at it (with how many), and the records
     * it points at itself. A screen uses it to offer the way from an order to its shipments, from an item to the orders it is on.
     */
    @GetMapping("/{id}/links")
    public Map<String, Object> links(@PathVariable String entity, @PathVariable long id, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        Map<String, Object> current = one(definition, id);
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        List<Map<String, Object>> from = new ArrayList<>(), to = new ArrayList<>();
        for (AppDefinitions.Stored other : definitions.all()) {
            AppDefinitions.Definition user = other.definition();
            // Screens not yet published are seen by administrators only (as everywhere else).
            if ((!other.status().equals("PUBLISHED") && !admin) || user.fields() == null) continue;
            for (AppDefinitions.Field field : user.fields())
                if (field.ref() != null && field.ref().entity().equals(entity)) {
                    long count = count(user.key(), field.name(), id);
                    if (count > 0) from.add(link(other, field.name(), field.label(), count));
                }
            for (AppDefinitions.LineSet set : user.lineSets())
                for (AppDefinitions.Field field : set.fields())
                    if (field.ref() != null && field.ref().entity().equals(entity)) {
                        Long users = store.countLines(user, set, field, String.valueOf(id));
                        if (users != null && users > 0) from.add(link(other, set.name() + "." + field.name(), set.label() + " " + field.label(), users));
                    }
        }
        @SuppressWarnings("unchecked") Map<String, String> names = current.get("_names") instanceof Map<?, ?> held ? (Map<String, String>) held : Map.of();
        List<Map<String, Object>> page = new ArrayList<>(List.of(current));
        named(definition, page);
        @SuppressWarnings("unchecked") Map<String, String> shown = (Map<String, String>) current.getOrDefault("_names", names);
        for (AppDefinitions.Field field : definition.fields())
            if (field.ref() != null && current.get(field.name()) instanceof Number target) {
                AppDefinitions.Stored pointed = definitions.find(field.ref().entity());
                if (pointed == null) continue;
                Map<String, Object> out = link(pointed, "id", field.label(), 1);
                out.put("id", target.longValue());
                out.put("name", shown.getOrDefault(field.name(), String.valueOf(target)));
                to.add(out);
            }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("from", from);
        out.put("to", to);
        return out;
    }

    private static Map<String, Object> link(AppDefinitions.Stored other, String field, String label, long count) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("entity", other.definition().key());
        out.put("title", other.definition().title());
        out.put("programCode", other.programCode());
        out.put("field", field);
        out.put("label", label);
        out.put("count", count);
        return out;
    }

    /** Who changed this record, when and what (newest first). */
    @GetMapping("/{id}/history")
    public List<Map<String, Object>> history(@PathVariable String entity, @PathVariable long id, Authentication authentication) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        List<Map<String, Object>> entries = history.read(definition, id);       // a deleted record still has its history
        if (entries.isEmpty()) one(definition, id);
        return entries;
    }

    /** A status action of the definition (e.g. confirm, cancel): allowed from the current status and by the rules.
     *  With ?check=true the same judgement is made and nothing is changed. */
    /** A screen sends, in the X-Seen header, when the record was last changed as it showed it: a record changed since (by someone else) is not
     *  changed, deleted or moved on from what was seen - the person queries again first. Without the header nothing is compared. */
    private static void unchanged(Map<String, Object> current, String word) {
        if (!(org.springframework.web.context.request.RequestContextHolder.getRequestAttributes() instanceof org.springframework.web.context.request.ServletRequestAttributes attributes)) return;
        String seen = attributes.getRequest().getHeader("X-Seen");
        if (seen == null || seen.isBlank() || current == null) return;
        if (!seen.trim().equals(String.valueOf(current.get("updatedAt"))))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "조회한 뒤에 다른 사람이 바꾼 자료입니다. 다시 조회한 뒤 " + word + "하세요.");
    }

    @PostMapping("/{id}/actions/{action}")
    @Transactional
    public Map<String, Object> act(@PathVariable String entity, @PathVariable long id, @PathVariable String action,
                                   @RequestParam(defaultValue = "false") boolean check, Authentication authentication) {
        dataOnly(definition(entity, authentication), authentication);
        return perform(entity, id, action, check, authentication, false);
    }

    /** fromWorkScreen: the action comes through a work screen that lists it; an action marked separate is taken only that way. */
    @Transactional
    public Map<String, Object> perform(String entity, long id, String action, boolean check, Authentication authentication, boolean fromWorkScreen) {
        return perform(entity, id, action, check, authentication, fromWorkScreen, false);
    }
    /** seenNow: the record was just written in this same request (the fields a work screen asks with the action): what was seen is not compared again. */
    @Transactional
    public Map<String, Object> perform(String entity, long id, String action, boolean check, Authentication authentication, boolean fromWorkScreen, boolean seenNow) {
        AppDefinitions.Definition definition = definition(entity, authentication);
        AppDefinitions.Action chosen = definition.status() == null ? null
                : definition.status().actions().stream().filter(candidate -> candidate.name().equals(action)).findFirst().orElse(null);
        if (chosen == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "이 자료에 없는 동작입니다: " + action);
        if (chosen.separate() && !fromWorkScreen)
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, chosen.label() + " 은(는) 이 화면이 아니라 그 일을 하는 화면에서 합니다.");
        Map<String, Object> current = one(definition, id);
        if (!check && !seenNow) unchanged(current, chosen.label());
        String status = (String) current.get("status");
        if (!chosen.from().contains(status))
            throw new ResponseStatusException(HttpStatus.CONFLICT, definition.status().label(status) + " 상태에서는 " + chosen.label() + "할 수 없습니다.");
        rules(definition, id, action);
        quantities.open(definition, id, chosen.label());          // a record whose stock is in a closed month stays as it is
        locks.open(definition, lockDay(definition, current), chosen.label());
        if (check) return current;   // asked only whether it would be allowed: nothing changes
        store.setStatus(entity, id, chosen.to(), authentication.getName());
        history.note(entity, id, "STATUS", action, false, null, null, status, chosen.to(), authentication.getName());
        effects(definition, id, action, authentication.getName(), 0);
        return one(definition, id);
    }

    /** Master data drawn on: the master record(s) matching this record, each of their lines made into a record of `into` (one item each). */
    private void expanded(AppDefinitions.Definition definition, long id, JsonNode source, AppDefinitions.Expand expand, String user, int depth) {
        AppDefinitions.Stored master = definitions.find(expand.from()), target = definitions.find(expand.into());
        if (master == null || target == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "펼칠 기준 정보나 만들 자료의 화면이 없어졌습니다.");
        List<AppDefinitions.Field> masterLines = master.definition().lines() != null ? master.definition().lines().fields() : master.definition().fields();
        Map.Entry<String, String> first = expand.match().entrySet().iterator().next();
        JsonNode wanted = source.get(first.getValue());
        if (wanted == null || wanted.isNull()) return;
        List<Map<String, Object>> lines = store.lineRows(master.definition(), first.getKey(), wanted.asString(), null);
        java.time.LocalDate day = expand.at() != null && source.hasNonNull(expand.at()) ? java.time.LocalDate.parse(source.get(expand.at()).asString()) : today();
        lines.removeIf(line -> {           // every other match field must agree as well, and a master with a period must be valid on the day
            @SuppressWarnings("unchecked") Map<String, Object> owner = (Map<String, Object>) line.get("_owner");
            for (Map.Entry<String, String> entry : expand.match().entrySet())
                if (!String.valueOf(owner.get(entry.getKey())).equals(source.hasNonNull(entry.getValue()) ? source.get(entry.getValue()).asString() : "null")) return true;
            return master.definition().effective() != null && !master.definition().effective().holds(mapper.valueToTree(owner), day);
        });
        if (lines.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, master.definition().title().replaceAll("\\s*(등록|관리|입력)$", "") + " 에 맞는 기준 정보가 없어 펼칠 수 없습니다 (" + first.getKey() + " = " + wanted.asString() + (master.definition().effective() != null ? ", " + day + " 에 유효한 것" : "") + "). 먼저 기준 정보를 등록하세요.");
        double times = expand.quantityTimes() == null ? 1 : source.path(expand.quantityTimes()).asDouble(0);
        Map<String, Map<Long, Map<String, Object>>> far = new LinkedHashMap<>();          // lines of other masters a layer-3 line points at
        int number = 0;
        for (Map<String, Object> line : lines) {
            number++;
            ObjectNode body = mapper.createObjectNode();
            for (Map.Entry<String, String> entry : expand.set().entrySet()) {
                String value = entry.getValue();
                if (!value.startsWith("line.")) { carry(body, entry.getKey(), value, source, id); continue; }
                String[] path = value.substring(5).split("\\.");
                Object found = line.get(path[0]);
                if (path.length > 1 && found instanceof Number pointed) {
                    AppDefinitions.Field via = masterLines.stream().filter(field -> field.name().equals(path[0])).findFirst().orElse(null);
                    AppDefinitions.Stored other = via == null || via.ref() == null ? null : definitions.find(via.ref().entity());
                    if (other != null) {
                        Map<Long, Map<String, Object>> known = far.computeIfAbsent(other.definition().key(), key -> new LinkedHashMap<>());
                        if (!known.containsKey(pointed.longValue()))
                            for (Map<String, Object> row : store.lineRows(other.definition(), null, null, List.of(pointed.longValue()))) known.put(((Number) row.get("id")).longValue(), row);
                        found = known.getOrDefault(pointed.longValue(), Map.of()).get(path[1]);
                    }
                }
                body.set(entry.getKey(), mapper.valueToTree(found));
            }
            double each = line.get(expand.quantityLine()) instanceof Number amount ? amount.doubleValue() : 0;
            body.put(expand.quantityInto(), java.math.BigDecimal.valueOf(each * times).stripTrailingZeros().doubleValue());
            try { insert(target.definition(), body, user, depth + 1); }
            catch (ResponseStatusException refused) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, target.definition().title() + " 을(를) 펼쳐 만들지 못해 취소했습니다 (" + number + "번째 줄): " + refused.getReason());
            }
        }
    }

    /** The earlier records this one draws on that are now used up in full take the action (an order shipped in full becomes 출하 완료). */
    private void filled(AppDefinitions.Definition definition, JsonNode source, AppDefinitions.Fill fill, String user, int depth) {
        AppDefinitions.Limit limit = definition.limits().stream().filter(candidate -> candidate.entity().equals(fill.entity()) && candidate.entityBy().contains("id")).findFirst().orElse(null);
        AppDefinitions.Stored target = definitions.find(fill.entity());
        if (limit == null || target == null || target.definition().status() == null) return;
        AppDefinitions.Action wanted = target.definition().status().actions().stream().filter(candidate -> candidate.name().equals(fill.action())).findFirst().orElse(null);
        if (wanted == null) return;
        int at = limit.entityBy().indexOf("id");
        String pointer = limit.by().get(at);
        java.util.Set<String> ids = new java.util.LinkedHashSet<>();
        if (limit.lines()) for (JsonNode line : source.path("lines")) { JsonNode from = line.has(pointer) ? line : source; if (from.hasNonNull(pointer)) ids.add(from.get(pointer).asString()); }
        else if (source.hasNonNull(pointer)) ids.add(source.get(pointer).asString());
        if (ids.isEmpty()) return;
        Map<String, Double> allowed = sums(fill.entity(), limit.entityField(), limit.entityLines(), limit.entityBy(), limit.entityIgnore(), null);
        Map<String, Double> taken = sums(definition.key(), limit.field(), limit.lines(), limit.by(), limit.ignore(), null);
        for (String id : ids) {
            boolean any = false, full = true;
            for (Map.Entry<String, Double> entry : allowed.entrySet()) {
                String[] parts = entry.getKey().split(SEPARATOR, -1);
                if (parts.length <= at || !parts[at].equals(id)) continue;
                any = true;
                if (taken.getOrDefault(entry.getKey(), 0.0) < entry.getValue() - 1e-9) { full = false; break; }
            }
            if (!any || !full || !id.matches("\\d{1,18}")) continue;
            long other = Long.parseLong(id);
            String now = store.has(fill.entity(), other) ? store.status(fill.entity(), other) : null;
            if (now == null || !wanted.from().contains(now)) continue;          // not where the action starts (or already past it): left as it is
            rules(target.definition(), other, wanted.name());
            quantities.open(target.definition(), other, wanted.label());
            locks.open(target.definition(), lockDay(target.definition(), one(target.definition(), other)), wanted.label());
            store.setStatus(fill.entity(), other, wanted.to(), user);
            history.note(fill.entity(), other, "STATUS", wanted.name(), true, null, null, now, wanted.to(), user);
            effects(target.definition(), other, wanted.name(), user, depth + 1);
        }
    }

    /** Down the flow: every record of the cascade's entity that points at this one and stands where the action starts takes it too
     *  (closing a work order early closes its planned issues; reopening it reopens them). Those already past that point are left as they are. */
    private void cascaded(AppDefinitions.Definition definition, long id, AppDefinitions.Cascade cascade, String user, int depth) {
        AppDefinitions.Stored target = definitions.find(cascade.entity());
        if (target == null || !RecordStore.keeps(target.definition())) throw new ResponseStatusException(HttpStatus.CONFLICT, "따라 처리할 자료 " + cascade.entity() + " 화면이 없어졌습니다.");
        AppDefinitions.Action wanted = target.definition().status() == null ? null
                : target.definition().status().actions().stream().filter(candidate -> candidate.name().equals(cascade.action())).findFirst().orElse(null);
        if (wanted == null) return;
        for (Map<String, Object> row : jdbc.queryForList("SELECT id, status FROM " + RecordStore.table(cascade.entity()) + " WHERE " + RecordStore.column(cascade.via()) + " = ? ORDER BY id", id)) {
            long other = ((Number) row.get("id")).longValue();
            String now = (String) row.get("status");
            if (now == null || !wanted.from().contains(now)) continue;
            rules(target.definition(), other, wanted.name());
            quantities.open(target.definition(), other, wanted.label());
            locks.open(target.definition(), lockDay(target.definition(), one(target.definition(), other)), wanted.label());
            store.setStatus(cascade.entity(), other, wanted.to(), user);
            history.note(cascade.entity(), other, "STATUS", wanted.name(), true, null, null, now, wanted.to(), user);
            effects(target.definition(), other, wanted.name(), user, depth + 1);
        }
    }

    /** What follows by itself from creating a record or taking a status action. A refusal anywhere undoes the whole request. */
    private void effects(AppDefinitions.Definition definition, long id, String on, String user, int depth) {
        if (definition.effects().isEmpty()) return;
        if (depth > 3) throw new ResponseStatusException(HttpStatus.CONFLICT, "따라 일어나는 일이 서로 꼬리를 물고 있습니다 (" + definition.title() + ").");
        JsonNode source = null;
        for (AppDefinitions.Effect effect : definition.effects()) {
            if (!effect.on().equals(on)) continue;
            if (source == null) source = mapper.readTree(store.data(definition, id));
            if (effect.fill() != null) { filled(definition, source, effect.fill(), user, depth); continue; }
            if (effect.expand() != null) { expanded(definition, id, source, effect.expand(), user, depth); continue; }
            if (effect.cascade() != null) { cascaded(definition, id, effect.cascade(), user, depth); continue; }
            String targetKey = effect.create() != null ? effect.create().entity() : definition.field(effect.act().via()).ref().entity();
            AppDefinitions.Stored target = definitions.find(targetKey);
            if (target == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "따라 처리할 자료 " + targetKey + " 화면이 없어졌습니다.");
            if (effect.create() != null) {
                ObjectNode body = mapper.createObjectNode();
                for (Map.Entry<String, String> entry : effect.create().set().entrySet()) carry(body, entry.getKey(), entry.getValue(), source, id);
                if (effect.create().lines() != null) {
                    ArrayNode lines = mapper.createArrayNode();
                    for (JsonNode line : source.path("lines")) {
                        ObjectNode made = mapper.createObjectNode();
                        for (Map.Entry<String, String> entry : effect.create().lines().set().entrySet()) if (line.hasNonNull(entry.getValue())) made.set(entry.getKey(), line.get(entry.getValue()));
                        lines.add(made);
                    }
                    body.set("lines", lines);
                }
                try { insert(target.definition(), body, user, depth + 1); }
                catch (ResponseStatusException refused) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, target.definition().title() + " 을(를) 함께 만들지 못해 취소했습니다: " + refused.getReason());
                }
            } else {
                JsonNode pointed = source.get(effect.act().via());
                if (pointed == null || pointed.isNull()) continue;                       // nothing chosen: nothing to act on
                long other = pointed.asLong();
                AppDefinitions.Action wanted = target.definition().status().actions().stream().filter(candidate -> candidate.name().equals(effect.act().action())).findFirst().orElse(null);
                List<String> now = store.has(targetKey, other) ? java.util.Arrays.asList(store.status(targetKey, other)) : List.of();
                if (wanted == null || now.isEmpty() || now.get(0) == null || !wanted.from().contains(now.get(0))) continue;   // already past that point (or gone): leave it as it is
                rules(target.definition(), other, wanted.name());
                quantities.open(target.definition(), other, wanted.label());
                locks.open(target.definition(), lockDay(target.definition(), one(target.definition(), other)), wanted.label());
                store.setStatus(targetKey, other, wanted.to(), user);
                history.note(targetKey, other, "STATUS", wanted.name(), true, null, null, now.get(0), wanted.to(), user);
                effects(target.definition(), other, wanted.name(), user, depth + 1);
            }
        }
    }

    private static void carry(ObjectNode body, String into, String from, JsonNode source, long id) {
        if (from.equals("id")) body.put(into, id);
        else if (from.equals("today")) body.put(into, today().toString());
        else if (source.hasNonNull(from)) body.set(into, source.get(from));
    }

    /** The business day: the calendar of the place the system is used in (APP_TIMEZONE, default Asia/Seoul), not the server's clock zone. */
    static java.time.LocalDate today() { return java.time.LocalDate.now(java.time.ZoneId.of(System.getenv().getOrDefault("APP_TIMEZONE", "Asia/Seoul"))); }

    static final String SEPARATOR = "\u0001";
    /** Sum of a number field per group of key fields over stored rows (lines or headers), skipping rows in the ignored statuses and one row by id. */
    Map<String, Double> sums(String entity, String field, boolean lines, List<String> by, List<String> ignore, Long except) {
        Map<String, Double> out = new LinkedHashMap<>();
        AppDefinitions.Stored stored = definitions.find(entity);
        if (stored == null || !RecordStore.keeps(stored.definition())) return out;
        for (Map.Entry<List<String>, Double> entry : store.sums(stored.definition(), field, lines, by, ignore, except)) out.merge(String.join(SEPARATOR, entry.getKey()), entry.getValue(), Double::sum);
        return out;
    }
    private void add(Map<String, Double> out, JsonNode header, Long id, String field, boolean lines, List<String> by) {
        List<JsonNode> units = new ArrayList<>();
        if (lines) { for (JsonNode line : header.path("lines")) units.add(line); } else units.add(header);
        for (JsonNode unit : units) {
            List<String> keys = new ArrayList<>();
            for (String name : by) {
                JsonNode from = lines && unit.has(name) ? unit : header;
                keys.add(name.equals("id") ? String.valueOf(id) : from.hasNonNull(name) ? from.get(name).asString() : "");
            }
            if (field == null || field.isEmpty()) { out.merge(String.join(SEPARATOR, keys), 1.0, Double::sum); continue; }     // once: the record (line) itself
            JsonNode holder = lines && unit.has(field) ? unit : header;
            if (holder.hasNonNull(field) && holder.get(field).isNumber()) out.merge(String.join(SEPARATOR, keys), holder.get(field).asDouble(), Double::sum);
        }
    }

    /** Limits: with this record as it is about to be stored, no group of this entity may add up to more than the other entity allows. */
    private void limits(AppDefinitions.Definition definition, ObjectNode data, Long self, String status) {
        for (AppDefinitions.Limit limit : definition.limits()) {
            if (status != null && limit.ignore().contains(status)) continue;
            closedEarlier(definition, limit, data, self);
            Map<String, Double> mine = sums(definition.key(), limit.field(), limit.lines(), limit.by(), limit.ignore(), self);
            Map<String, Double> incoming = new LinkedHashMap<>();
            add(incoming, data, self, limit.field(), limit.lines(), limit.by());
            if (incoming.isEmpty()) continue;
            Map<String, Double> allowed = sums(limit.entity(), limit.entityField(), limit.entityLines(), limit.entityBy(), limit.entityIgnore(), null);
            for (Map.Entry<String, Double> entry : incoming.entrySet()) {
                if (entry.getKey().replace(SEPARATOR, "").isEmpty()) continue;            // nothing to match on (the pointing field is empty)
                double total = mine.getOrDefault(entry.getKey(), 0.0) + entry.getValue(), cap = allowed.getOrDefault(entry.getKey(), 0.0);
                if (total > cap + 1e-9) throw bad(limit.once() ? limit.message() : limit.counted() ? limit.message() + " (한도 " + plain(cap) + "건)" : limit.message() + " (한도 " + plain(cap) + ", 이번 저장 후 합계 " + plain(total) + ")");
            }
        }
    }

    /** A finished earlier record (closed early, cancelled, done - its status says closed) takes nothing more: a record newly pointing at it is refused. */
    private void closedEarlier(AppDefinitions.Definition definition, AppDefinitions.Limit limit, ObjectNode data, Long self) {
        int at = limit.entityBy().indexOf("id");
        AppDefinitions.Stored earlier = at < 0 ? null : definitions.find(limit.entity());
        if (earlier == null || earlier.definition().status() == null || earlier.definition().status().closed().isEmpty()) return;
        String pointer = limit.by().get(at);
        java.util.Set<String> wanted = pointed(data, pointer), had = new java.util.LinkedHashSet<>();
        if (self != null) { String stored = store.data(definition, self); if (stored != null) had = pointed(mapper.readTree(stored), pointer); }
        for (String value : wanted) {
            if (had.contains(value) || !value.matches("\\d{1,18}")) continue;
            String now = store.has(limit.entity(), Long.parseLong(value)) ? store.status(limit.entity(), Long.parseLong(value)) : null;
            if (earlier.definition().status().isClosed(now))
                throw bad(earlier.definition().title().replaceAll("\\s*(등록|관리|입력)$", "") + " 이(가) 「" + earlier.definition().status().label(now) + "」 상태라 더 이어서 등록할 수 없습니다.");
        }
    }
    private static java.util.Set<String> pointed(JsonNode data, String field) {
        java.util.Set<String> out = new java.util.LinkedHashSet<>();
        if (data.hasNonNull(field)) out.add(data.get(field).asString());
        for (JsonNode line : data.path("lines")) if (line.hasNonNull(field)) out.add(line.get(field).asString());
        return out;
    }

    /** Checks inside one record: two dates or two numbers that must stand in a given order. */
    private void checks(AppDefinitions.Definition definition, ObjectNode data) {
        for (AppDefinitions.Check check : definition.checks()) {
            List<JsonNode> units = new ArrayList<>();
            if (check.lines()) { for (JsonNode line : data.path("lines")) units.add(line); } else units.add(data);
            for (JsonNode unit : units) {
                if (!unit.hasNonNull(check.left())) continue;
                JsonNode left = unit.get(check.left());
                if (!check.right().equals("today") && !unit.hasNonNull(check.right())) continue;       // an empty side has nothing to be compared with
                int order = left.isNumber() ? Double.compare(left.asDouble(), unit.get(check.right()).asDouble())
                        : left.asString().compareTo(check.right().equals("today") ? today().toString() : unit.get(check.right()).asString());
                boolean holds = switch (check.op()) { case ">" -> order > 0; case ">=" -> order >= 0; case "<" -> order < 0; case "<=" -> order <= 0; case "==" -> order == 0; default -> order != 0; };
                if (!holds) throw bad(check.message());
            }
        }
    }

    /** Locked statuses and the definition's rules for update/delete. */
    private void guard(AppDefinitions.Definition definition, long id, String status, String action, String word) {
        if (definition.status() != null && status != null && definition.status().locked().contains(status))
            throw new ResponseStatusException(HttpStatus.CONFLICT, definition.status().label(status) + " 상태의 자료는 " + word + "할 수 없습니다.");
        rules(definition, id, action);
    }

    private void rules(AppDefinitions.Definition definition, long id, String action) {
        for (AppDefinitions.Rule rule : definition.rules())
            if (rule.action().equals(action) && count(rule.entity(), rule.field(), id) > 0)
                throw new ResponseStatusException(HttpStatus.CONFLICT, rule.message());
    }

    private int count(String entity, String field, long id) {
        AppDefinitions.Stored other = definitions.find(entity);
        if (other != null && other.definition().field(field) == null)          // pointed at from the other entity's lines
            for (AppDefinitions.LineSet set : other.definition().lineSets())
                for (AppDefinitions.Field line : set.fields())
                    if (line.name().equals(field)) return (int) store.countLines(other.definition(), set, line, String.valueOf(id));
        return (int) store.countWhere(entity, field, String.valueOf(id), null);
    }

    private String nextSerial(String entity, AppDefinitions.Field field) {
        String head = field.prefix() + "-" + today().format(java.time.format.DateTimeFormatter.ofPattern("yyMM")) + "-";
        jdbc.queryForList("SELECT pg_advisory_xact_lock(hashtext(?))", entity + ":" + field.name());   // one number at a time per series
        String last = store.highest(entity, field.name(), head);
        int next = last == null ? 1 : Integer.parseInt(last.substring(head.length())) + 1;
        return head + String.format("%04d", next);
    }

    /** The definition, when this user may use it: drafts are for administrators (and the checks that run as one). */
    private AppDefinitions.Definition definition(String entity, Authentication authentication) {
        AppDefinitions.Stored stored = definitions.find(entity);
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        if (stored == null || (!stored.status().equals("PUBLISHED") && !admin)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "없는 화면입니다: " + entity);
        if (stored.definition().summary() != null || stored.definition().dashboard() != null || stored.definition().over() != null || stored.definition().take() != null || stored.definition().ledgerView() != null || stored.definition().calendar() != null || stored.definition().tree() != null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "집계 화면에는 저장하는 자료가 없습니다: " + entity);
        return stored.definition();
    }

    /** The body reduced to the defined fields with every built-in rule checked; computed values are worked out here. */
    /** Values found in master data: an empty field a lookup fills (a value typed by hand stays). A required one that nothing gives is refused here, saying where it was looked for. */
    private JsonNode looked(AppDefinitions.Definition definition, JsonNode body) {
        if (definition.lookups().isEmpty() || body == null || !body.isObject()) return body;
        ObjectNode out = ((ObjectNode) body).deepCopy();
        Map<String, AppDefinitions.Lookup> tried = new LinkedHashMap<>();
        for (AppDefinitions.Lookup lookup : definition.lookups())
            for (Map.Entry<String, String> entry : lookup.set().entrySet()) {
                if (out.hasNonNull(entry.getKey()) && !out.get(entry.getKey()).asString().isBlank()) continue;
                tried.putIfAbsent(entry.getKey(), lookup);
                JsonNode found = found(lookup, out);
                if (found != null && found.hasNonNull(entry.getValue())) out.set(entry.getKey(), found.get(entry.getValue()));
            }
        for (Map.Entry<String, AppDefinitions.Lookup> entry : tried.entrySet()) {
            AppDefinitions.Field field = definition.field(entry.getKey());
            if (field != null && field.required() && (!out.hasNonNull(entry.getKey()) || out.get(entry.getKey()).asString().isBlank())) {
                AppDefinitions.Lookup lookup = entry.getValue();
                AppDefinitions.Stored master = definitions.find(lookup.from());
                String by = String.join("·", lookup.match().values().stream().map(name -> definition.field(name) == null ? name : definition.field(name).label()).toList());
                String day = lookup.at() != null && out.hasNonNull(lookup.at()) ? out.get(lookup.at()).asString().replace('-', '/') : today().toString().replace('-', '/');
                throw bad((master == null ? lookup.from() : "「" + master.definition().title() + "」") + "에 이 " + by + "의 " + day + " 기준 " + field.label() + "이(가) 없습니다. "
                        + field.label() + "을(를) 직접 적거나 먼저 등록하세요.");
            }
        }
        return out;
    }
    /** The master record a lookup finds for these values: the one whose match fields agree, valid on the day when it has a period (the latest start first). */
    private JsonNode found(AppDefinitions.Lookup lookup, JsonNode values) {
        AppDefinitions.Stored master = definitions.find(lookup.from());
        if (master == null) return null;
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder();
        for (Map.Entry<String, String> entry : lookup.match().entrySet()) {
            JsonNode value = values.get(entry.getValue());
            if (value == null || value.isNull() || value.asString().isBlank()) return null;          // nothing to look with yet
            where.append(" AND app_records.data->>'").append(entry.getKey().replace("'", "")).append("' = ?");
            args.add(value.asString());
        }
        String order = "";
        AppDefinitions.Effective period = master.definition().effective();
        if (period != null) {
            String day = lookup.at() != null && values.hasNonNull(lookup.at()) && !values.get(lookup.at()).asString().isBlank()
                    ? values.get(lookup.at()).asString().replace('/', '-') : today().toString();
            where.append(" AND app_records.data->>'").append(period.from()).append("' <= ?");
            args.add(day);
            if (period.to() != null) { where.append(" AND (app_records.data->>'").append(period.to()).append("' IS NULL OR app_records.data->>'").append(period.to()).append("' >= ?)"); args.add(day); }
            order = " ORDER BY app_records.data->>'" + period.from() + "' DESC";
        }
        List<String> rows = jdbc.queryForList("SELECT app_records.data::text FROM " + store.source(lookup.from()) + " app_records WHERE TRUE" + where + order + " LIMIT 1", String.class, args.toArray());
        return rows.isEmpty() ? null : mapper.readTree(rows.get(0));
    }
    /** What the lookups would put in, for the values on the form now (a screen fills the fields as the customer, item or date is chosen). */
    @PostMapping("/_lookup")
    public Map<String, Object> lookup(@PathVariable String entity, @RequestBody JsonNode body, Authentication authentication) {
        return lookedUp(definition(entity, authentication), body);
    }
    public Map<String, Object> lookedUp(AppDefinitions.Definition definition, JsonNode body) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (body == null || !body.isObject()) return out;
        for (AppDefinitions.Lookup lookup : definition.lookups()) {
            JsonNode found = null;
            boolean looked = false;
            for (Map.Entry<String, String> entry : lookup.set().entrySet()) {
                if (out.get(entry.getKey()) != null) continue;                 // an earlier lookup already gave it
                if (!looked) { found = found(lookup, body); looked = true; }
                out.put(entry.getKey(), found != null && found.hasNonNull(entry.getValue()) ? mapper.treeToValue(found.get(entry.getValue()), Object.class) : null);
            }
        }
        return out;
    }

    private ObjectNode validated(AppDefinitions.Definition definition, JsonNode body, Map<String, Object> current) {
        if (body == null || !body.isObject()) throw bad("요청 본문은 JSON 객체여야 합니다.");
        ObjectNode out = row(definition.fields(), body, "", null, current);
        for (AppDefinitions.Field field : definition.fields())
            if (field.unique() && out.hasNonNull(field.name())) {
                Long self = current == null ? -1L : ((Number) current.get("id")).longValue();
                if (store.countWhere(definition.key(), field.name(), out.get(field.name()).asString(), self) > 0)
                    throw bad(field.label() + " " + out.get(field.name()).asString() + " 은(는) 이미 있습니다.");
            }
        Long self = current == null ? null : ((Number) current.get("id")).longValue();
        for (List<String> group : definition.uniqueBy() == null ? List.<List<String>>of() : definition.uniqueBy()) {        // a combination no two records may share
            Map<String, JsonNode> values = new LinkedHashMap<>();
            for (String name : group) values.put(name, out.get(name));
            if (values.values().stream().allMatch(value -> value == null || value.isNull())) continue;
            if (store.countCombination(definition, values, self) > 0)
                throw bad(group.stream().map(name -> definition.field(name).label()).collect(java.util.stream.Collectors.joining("·")) + " 이(가) 같은 " + definition.title().replaceAll("\\s*(등록|관리|입력)$", "") + " 이(가) 이미 있습니다.");
        }
        if (definition.effective() != null && out.hasNonNull(definition.effective().from())) {       // a period: sound, and not overlapping another of the same kind
            AppDefinitions.Effective period = definition.effective();
            String from = out.get(period.from()).asString(), to = period.to() != null && out.hasNonNull(period.to()) ? out.get(period.to()).asString() : null;
            Map<String, JsonNode> by = new LinkedHashMap<>();
            for (String name : period.by()) by.put(name, out.get(name));
            if (store.countOverlap(definition, by, from, to, self) > 0)
                throw bad((period.by().isEmpty() ? "" : period.by().stream().map(name -> definition.field(name).label()).collect(java.util.stream.Collectors.joining("·")) + " 이(가) 같은 ")
                        + "자료의 적용 기간이 겹칩니다 (" + from + " ~ " + (to == null ? "계속" : to) + "). 앞의 기간을 먼저 닫거나 날짜를 바꾸세요.");
        }
        for (AppDefinitions.LineSet rule : definition.lineSets()) {       // the first table of lines, then any further ones: each kept under its own name
            JsonNode lines = body.get(rule.name());
            int count = lines != null && lines.isArray() ? lines.size() : 0;
            if (count < rule.min()) throw bad(rule.label() + "을(를) " + (rule.min() == 1 ? "한" : String.valueOf(rule.min())) + " 줄 이상 입력하세요.");
            if (rule.max() != null && count > rule.max()) throw bad(rule.label() + "은(는) " + rule.max() + "줄까지만 넣을 수 있습니다.");
            if (lines == null || !lines.isArray()) lines = mapper.createArrayNode();
            ArrayNode stored = mapper.createArrayNode();
            int number = 0;
            for (JsonNode line : lines) {
                number++;
                ObjectNode item = row(rule.fields(), line, rule.label() + " " + number + "번째 줄의 ", body, null);
                compute(rule.fields(), item);
                if (line.hasNonNull("_line")) item.set("_line", line.get("_line"));       // the line's own id: kept, so what points at this line keeps pointing at it
                stored.add(item);
            }
            out.set(rule.name(), stored);
            for (AppDefinitions.Field field : rule.fields())          // unique in lines: the same value twice in this record's lines
                if (field.unique()) {
                    java.util.Set<String> seen = new java.util.HashSet<>();
                    int at = 0;
                    for (JsonNode item : stored) {
                        at++;
                        if (item.hasNonNull(field.name()) && !seen.add(item.get(field.name()).asString()))
                            throw bad(rule.label() + " " + at + "번째 줄의 " + field.label() + " 이(가) 앞의 줄과 겹칩니다. 한 건에 같은 " + field.label() + " 은(는) 한 줄만 넣습니다.");
                    }
                }
        }
        if (definition.noCycle() != null && out.hasNonNull(definition.noCycle().parent())) {      // a part may not be the item itself, nor lead back to it
            AppDefinitions.NoCycle cycle = definition.noCycle();
            long top = out.get(cycle.parent()).asLong();
            java.util.Set<Long> reached = new java.util.HashSet<>(), next = new java.util.HashSet<>();
            int at = 0;
            if (definition.field(cycle.child()) != null && out.hasNonNull(cycle.child())) {     // one pair per record
                if (out.get(cycle.child()).asLong() == top) throw bad(definition.field(cycle.child()).label() + " 이(가) " + definition.field(cycle.parent()).label() + " 자신입니다.");
                next.add(out.get(cycle.child()).asLong());
            }
            for (JsonNode item : definition.field(cycle.child()) != null ? mapper.createArrayNode() : out.path("lines")) {
                at++;
                if (!item.hasNonNull(cycle.child())) continue;
                if (item.get(cycle.child()).asLong() == top) throw bad(definition.lines().label() + " " + at + "번째 줄: " + definition.lines().fields().stream().filter(field -> field.name().equals(cycle.child())).findFirst().orElseThrow().label() + " 이(가) " + definition.field(cycle.parent()).label() + " 자신입니다.");
                next.add(item.get(cycle.child()).asLong());
            }
            for (int depth = 0; depth < 50 && !next.isEmpty(); depth++) {
                reached.addAll(next);
                java.util.Set<Long> further = new java.util.HashSet<>();
                for (Long found : store.childrenOf(definition, cycle.parent(), cycle.child(), next, self)) {
                    if (found == top) throw bad("순환이 생깁니다: 하위로 넣은 것 중에 다시 " + definition.field(cycle.parent()).label() + " 을(를) 하위로 품는 것이 있습니다.");
                    if (!reached.contains(found)) further.add(found);
                }
                next = further;
            }
        }
        for (AppDefinitions.Field field : definition.fields())
            if (field.sum() != null) {
                Object[] target = AppDefinitions.sumTarget(definition.lines(), definition.moreLines() == null ? List.of() : definition.moreLines(), field.sum());
                double total = 0;
                if (target != null) for (JsonNode item : out.path((String) target[0])) if (item.hasNonNull(((AppDefinitions.Field) target[1]).name())) total += item.get(((AppDefinitions.Field) target[1]).name()).asDouble();
                put(out, field.name(), rounded(total, field));
            }
        compute(definition.fields(), out);
        checks(definition, out);           // (the screen's own comparisons speak first, in its own words)
        for (AppDefinitions.NoOverlap span : definition.noOverlap()) {
            if (!out.hasNonNull(span.from()) || !out.hasNonNull(span.to())) continue;
            AppDefinitions.Field start = definition.field(span.from()), end = definition.field(span.to());
            if (out.get(span.to()).asString().compareTo(out.get(span.from()).asString()) < (start.type().equals("time") ? 1 : 0))
                throw bad(end.label() + "은(는) " + start.label() + "보다 " + (start.type().equals("time") ? "늦어야 합니다." : "앞설 수 없습니다."));
        }
        if (definition.effective() != null && definition.effective().to() != null && out.hasNonNull(definition.effective().to()) && out.hasNonNull(definition.effective().from())
                && out.get(definition.effective().to()).asString().compareTo(out.get(definition.effective().from()).asString()) < 0)
            throw bad(definition.field(definition.effective().to()).label() + "이(가) " + definition.field(definition.effective().from()).label() + "보다 앞설 수 없습니다.");
        for (AppDefinitions.Field field : definition.fields())   // a number once given stays; a new one is given by create()
            if (field.type().equals("serial") || field.type().equals("user")) out.put(field.name(), current == null ? null : (String) current.get(field.name()));
        return out;
    }

    private void compute(List<AppDefinitions.Field> fields, ObjectNode row) {
        for (AppDefinitions.Field field : fields)
            if (field.formula() != null) {
                Map<String, Double> values = new LinkedHashMap<>();
                for (AppDefinitions.Field other : fields)
                    if (other.type().equals("number") && other != field) values.put(other.name(), row.hasNonNull(other.name()) ? row.get(other.name()).asDouble() : null);
                Double result = Formula.evaluate(field.formula(), values);
                if (result == null) row.putNull(field.name()); else put(row, field.name(), rounded(result, field));
            }
    }

    /** A number as it reads in a message: 1,234,567.5 (the same form the screens use). */
    private static String plain(double value) { return new java.text.DecimalFormat("#,##0.######", java.text.DecimalFormatSymbols.getInstance(java.util.Locale.US)).format(value); }

    /** A computed number kept to the field's decimal places (half up, as on an invoice). */
    private static double rounded(double value, AppDefinitions.Field field) {
        return field.decimals() == null ? value : java.math.BigDecimal.valueOf(value).setScale(field.decimals(), java.math.RoundingMode.HALF_UP).doubleValue();
    }

    private static void put(ObjectNode row, String name, double value) {
        if (value == Math.rint(value) && Math.abs(value) < 1e15) row.put(name, (long) value); else row.put(name, value);
    }

    /** above: the record a line belongs to (a line's conditions may look at it). current: the record as stored, when it is being changed (what a locked field keeps). */
    private ObjectNode row(List<AppDefinitions.Field> fields, JsonNode body, String where, JsonNode above, Map<String, Object> current) {
        if (body == null || !body.isObject()) throw bad(where + "값은 JSON 객체여야 합니다.");
        ObjectNode out = mapper.createObjectNode();
        for (AppDefinitions.Field field : fields) {
            if (field.computed()) { out.putNull(field.name()); continue; }
            // A field that is not there under these values holds nothing and is asked for nothing.
            if (field.showWhen() != null && !field.showWhen().holds(body, above)) { if (field.type().equals("yesno")) out.put(field.name(), false); else out.putNull(field.name()); continue; }
            // A locked field keeps what the stored record has (a new record has nothing to keep: what was typed before the lock stays).
            // ... unless what it depends on was changed in this same saving (the field is filled from it: a new requirement brings its own material)
            if (field.lockWhen() != null && current != null && field.lockWhen().holds(body, above)
                    && String.valueOf(current.get(field.lockWhen().field())).equals(body.has(field.lockWhen().field()) ? body.get(field.lockWhen().field()).asString() : "null")) {
                out.set(field.name(), mapper.valueToTree(current.get(field.name()))); continue;
            }
            JsonNode value = body.get(field.name());
            boolean empty = value == null || value.isNull() || (value.isString() && value.asString().isBlank());
            if (field.type().equals("yesno")) { out.put(field.name(), !empty && (value.isBoolean() ? value.asBoolean() : yes(value.asString()))); continue; }
            if (empty) {
                if (field.required() || (field.requiredWhen() != null && field.requiredWhen().holds(body, above))) throw bad(where + field.label() + "을(를) 입력하세요.");
                out.putNull(field.name());
                continue;
            }
            switch (field.type()) {
                case "number" -> {
                    if (!value.isNumber() && !(value.isString() && value.asString().trim().matches("-?\\d{1,15}(\\.\\d{1,6})?"))) throw bad(where + field.label() + "은(는) 숫자여야 합니다.");
                    double number = value.isNumber() ? value.asDouble() : Double.parseDouble(value.asString().trim());
                    if (field.min() != null && number < field.min()) throw bad(where + field.label() + "은(는) " + plain(field.min()) + " 이상이어야 합니다.");
                    if (field.max() != null && number > field.max()) throw bad(where + field.label() + "은(는) " + plain(field.max()) + " 이하여야 합니다.");
                    if (field.decimals() != null && Math.abs(rounded(number, field) - number) > 1e-9)
                        throw bad(where + field.label() + "은(는) " + (field.decimals() == 0 ? "정수여야 합니다." : "소수 " + field.decimals() + "자리까지 적습니다."));
                    put(out, field.name(), number);
                }
                case "date" -> {
                    String text = value.asString().trim();
                    try { java.time.LocalDate.parse(text); } catch (java.time.format.DateTimeParseException error) { throw bad(where + field.label() + "은(는) 2026/01/15 같은 날짜여야 합니다."); }
                    out.put(field.name(), text);
                }
                case "time" -> {
                    String time = time(value.asString());
                    if (time == null) throw bad(where + field.label() + "은(는) 09:30 같은 시각이어야 합니다.");
                    out.put(field.name(), time);
                }
                case "code" -> {
                    String code = value.asString().trim();
                    if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_codes WHERE group_code = ? AND code = ?", Integer.class, field.codeGroup(), code) == 0)
                        throw bad(where + field.label() + ": 공통 코드 " + field.codeGroup() + " 에 없는 값입니다 (" + code + ").");
                    out.put(field.name(), code);
                }
                case "ref" -> {
                    if (!value.isNumber() && !(value.isString() && value.asString().trim().matches("\\d{1,15}"))) throw bad(where + field.label() + "은(는) 목록에서 골라야 합니다.");
                    long target = value.isNumber() ? value.asLong() : Long.parseLong(value.asString().trim());
                    if (field.ref().line()) {         // a line of another master: it must be there, and belong to the record this one goes with
                        Long owner = store.lineOwner(field.ref().entity(), target);
                        if (owner == null) throw bad(where + field.label() + ": 고른 줄이 없습니다.");
                        if (field.ref().within() != null) {
                            JsonNode mine = body.has(field.ref().within()) ? body.get(field.ref().within()) : above == null ? null : above.get(field.ref().within());
                            String theirs = store.data(field.ref().entity(), owner);
                            JsonNode value2 = theirs == null ? null : mapper.readTree(theirs).get(field.ref().withinTarget());
                            String a = mine == null || mine.isNull() ? "" : mine.asString(), b = value2 == null || value2.isNull() ? "" : value2.asString();
                            if (!a.equals(b)) throw bad(where + field.label() + ": 고른 줄이 이 자료의 " + field.ref().within() + " 와(과) 같은 " + field.ref().withinTarget() + " 의 것이 아닙니다 (다른 품목의 줄을 골랐습니다).");
                        }
                        out.put(field.name(), target);
                        continue;
                    }
                    if (!store.has(field.ref().entity(), target))
                        throw bad(where + field.label() + ": 고른 자료가 없습니다.");
                    out.put(field.name(), target);
                }
                default -> {
                    String text = value.asString().trim();
                    int limit = field.type().equals("memo") ? 10000 : 2000;
                    if (text.length() > limit) throw bad(where + field.label() + "은(는) " + plain(limit) + "자 이하여야 합니다.");
                    out.put(field.name(), text);
                }
            }
        }
        return out;
    }

    private Map<String, Object> one(AppDefinitions.Definition definition, long id) {
        List<Map<String, Object>> rows = jdbc.query("SELECT " + RecordStore.select(definition) + " FROM " + RecordStore.table(definition.key()) + " t WHERE t.id = ?",
                (row, index) -> view(definition, row.getLong("id"), row.getString("data"), row.getString("status"), row.getString("created_by"), row.getTimestamp("created_at"),
                        row.getString("updated_by"), row.getTimestamp("updated_at")), id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, definition.title() + " 자료를 찾지 못했습니다.");
        if (definition.ledger() != null) rows.get(0).put("_ledger", quantities.moves(definition.key(), id));      // the lots and cost its movements used
        rows.get(0).put("_files", jdbc.queryForObject("SELECT COUNT(*) FROM app_record_files WHERE entity_key = ? AND record_id = ?", Integer.class, definition.key(), id));
        return rows.get(0);
    }

    private Map<String, Object> view(AppDefinitions.Definition definition, long id, String data, String status, String createdBy, java.sql.Timestamp createdAt,
                                     String updatedBy, java.sql.Timestamp updatedAt) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.putAll(mapper.readValue(data, new tools.jackson.core.type.TypeReference<LinkedHashMap<String, Object>>() {}));
        if (definition.status() != null) {
            out.put("status", status);
            out.put("statusLabel", definition.status().label(status));
        }
        out.put("createdBy", createdBy);
        out.put("createdAt", createdAt == null ? null : createdAt.toLocalDateTime().toString());
        out.put("updatedBy", updatedBy);
        out.put("updatedAt", updatedAt == null ? null : updatedAt.toLocalDateTime().toString());
        return out;
    }

    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
}
