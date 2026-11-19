package com.example.localinventory.framework.app;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Entity definitions: what a definition may say (capabilities), reading and validating it.
 * A definition is data; nothing is generated or compiled when one is added or changed.
 */
@Service
public class AppDefinitions {
    public static final List<String> PICKS = List.of("dropdown", "search", "popup");
    public static final List<String> FIELD_TYPES = List.of("text", "number", "date", "time", "yesno", "memo", "code", "ref", "serial", "user");
    private static final Set<String> RESERVED = Set.of("id", "lines", "status", "statusLabel", "createdBy", "createdAt", "updatedBy", "updatedAt");
    private static final String KEY = "[a-z][a-z0-9_]{1,39}", NAME = "[a-z][A-Za-z0-9]{0,39}";
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();
    public AppDefinitions(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    /** columns: what the search window shows of the target (null = its first fields). code: the target's field shown before the
     *  name wherever the chosen record appears (null = the target's first field, when that is not the name itself). */
    /** line: the ref points at a LINE of the other entity (a step of an item's routing, a part of its BOM) - layer 3, master data built on
     *  layer-2 master data. within / withinTarget: the line must belong to a record of the other entity whose `withinTarget` equals this
     *  record's `within` (the routing of the same item as this record). */
    public record Ref(String entity, String label, List<String> columns, String code, boolean line, String within, String withinTarget) {
        public Ref(String entity, String label, List<String> columns, String code) { this(entity, label, columns, code, false, null, null); }
    }
    /** prefix: serial numbers. formula: computed from the row's numbers. sum: header total of a line field. fill: target field <- field of the chosen record.
     *  decimals: how many decimal places a number keeps (null = as typed, up to six). */
    public record Field(String name, String label, String type, boolean required, boolean search, String codeGroup, Ref ref,
                        String prefix, String formula, String sum, Map<String, String> fill, Double min, Double max, boolean unique, String pick, Integer decimals,
                        Condition showWhen, Condition requiredWhen, Condition lockWhen) {
        public Field(String name, String label, String type, boolean required, boolean search, String codeGroup, Ref ref,
                     String prefix, String formula, String sum, Map<String, String> fill, Double min, Double max, boolean unique, String pick, Integer decimals) {
            this(name, label, type, required, search, codeGroup, ref, prefix, formula, sum, fill, min, max, unique, pick, decimals, null, null, null);
        }
        /** Kept as text and searched by "contains". */
        public boolean wordy() { return type.equals("text") || type.equals("serial") || type.equals("memo"); }
        public boolean computed() { return formula != null || sum != null || type.equals("serial") || type.equals("user"); }
    }
    /** A field that depends on another field of the same row (or, in a line, of the record above it): it holds when that field's value is one of `is`
     *  (codes as stored, ids, "true"/"false" for a yes/no; "" = empty). showWhen: the field is there only then (else it is kept empty and asked for nothing);
     *  requiredWhen: it must be filled then; lockWhen: it cannot be changed then. */
    /** not: the condition holds when the value is NOT one of `is` ("isNot" as written: locked once a requirement is chosen = lockWhen {field, isNot: [""]}). */
    public record Condition(String field, List<String> is, boolean not) {
        public Condition(String field, List<String> is) { this(field, is, false); }
        public boolean holds(JsonNode row, JsonNode above) { return not != matches(row, above); }
        private boolean matches(JsonNode row, JsonNode above) {
            JsonNode value = row != null && row.has(field) ? row.get(field) : above == null ? null : above.get(field);
            String text = value == null || value.isNull() ? "" : value.isBoolean() ? String.valueOf(value.asBoolean()) : value.isNumber() ? java.math.BigDecimal.valueOf(value.asDouble()).stripTrailingZeros().toPlainString() : value.asString().trim();
            if (text.isEmpty() && is.contains("false")) return true;      // an unticked yes/no may not have been stored at all
            return is.contains(text);
        }
    }
    /** min/max: how many lines a record may have (min defaults to 1; max null = no limit). */
    public record Lines(String label, List<Field> fields, int min, Integer max) {}
    /** One table of lines by name: the first one ("lines") or a further one (moreLines), kept in the record under that name. */
    public record LineSet(String name, String label, List<Field> fields, int min, Integer max) {}
    public record StatusValue(String code, String label) {}
    /** separate: the action is not offered on the entity's own screen, only on a work screen (over) that lists it - who may take it is then a matter of who has that screen. */
    public record Action(String name, String label, List<String> from, String to, boolean separate) {}
    /** A work screen over another entity's records: only those in the given statuses, only the given actions, read-only unless edit. Its own program, so its own permission. */
    /** mine: only the records whose user field (the one who registered them) is the person signed in. */
    /** ask: the fields an action of this screen has written with it (a reason to reject, the time of leaving) - only those, row by row. */
    public record Over(String entity, List<String> statuses, List<String> actions, boolean edit, boolean create, boolean mine, Map<String, List<String>> ask) {
        public Over(String entity, List<String> statuses, List<String> actions, boolean edit) { this(entity, statuses, actions, edit, false, false, Map.of()); }
        public List<String> asked(String action) { return ask == null ? List.of() : ask.getOrDefault(action, List.of()); }
    }
    /** locked: the record itself can no longer be changed or deleted. closed: the record is finished - nothing follows it any more
     *  (a work order closed early: what it still left open is no longer offered, and no further record may point at it through a limit). */
    public record Status(String initial, List<StatusValue> values, List<Action> actions, List<String> locked, List<String> closed) {
        public Status(String initial, List<StatusValue> values, List<Action> actions, List<String> locked) { this(initial, values, actions, locked, List.of()); }
        public String label(String code) { return values.stream().filter(value -> value.code().equals(code)).map(StatusValue::label).findFirst().orElse(code); }
        public boolean isClosed(String code) { return closed != null && code != null && closed.contains(code); }
    }
    /** blockWhenReferenced: refuse `action` (delete, update or a status action) while rows of `entity` point here through `field`. */
    public record Rule(String type, String action, String entity, String field, String message) {}
    /** A screen that gathers another entity's rows: grouped (by a field; dates by day, month or year) and computed (sum, count ...). */
    public record Group(String field, String by, String label) {}
    /** between: instead of a number field, the days from one date field to another (how long something took). */
    public record Value(String label, String op, String field, List<String> between) {}
    public record Chart(String type, String value) {}
    /** Set one of the values against something: a plan kept in another entity (type plan: entity, field, groupBy = that entity's
     *  fields in the order of the summary's groupBy), or the same figure one month or one year earlier (type previous: by). */
    public record Compare(String type, String value, String label, String entity, String field, List<String> groupBy, String by, boolean lines, String balance) {}
    public record Summary(String entity, boolean lines, List<Group> groupBy, List<Value> values, List<String> filters, Chart chart,
                          Compare compare, boolean share, Integer top, boolean cumulative) {}
    public static final List<String> OPS = List.of("sum", "count", "avg", "min", "max"), DATE_PARTS = List.of("day", "month", "year"), CHARTS = List.of("bar", "line", "pie");
    /** How one record is printed as a paper form: its heading, the approval boxes and a closing note. */
    public record Print(String title, List<String> signers, String note, boolean logo, boolean company, String receiver, List<String> fields, List<String> columns, Double vat) {}
    /** A month calendar of another entity's records: each on its date (to `end` when it has one), read as `label`. */
    public record Calendar(String entity, String date, String end, String label) {}
    /** A hierarchy. Without `child`: the entity's own records under their parent (a ref to the same entity) - an organisation, a classification.
     *  With `child`: the entity holds pairs (parent, child) that both point at another entity - a bill of materials; the tree is of those records. */
    public record Tree(String entity, String parent, String child, String label, List<String> columns) {}
    /** A screen that registers records of `entity` from what an earlier stage (`from`) still leaves open, in a list: query, tick rows, set the
     *  quantity in the row, save - no form. What is open is told by the limit `entity` has against `from` (its quantity may not exceed the earlier one's).
     *  set / lineSet: further fields of the new record <- fields of the earlier one. statuses: which earlier records are listed.
     *  group: how chosen rows become records by default - "source" (one new record per earlier record) or "same" (rows whose values above the lines are
     *  the same go into one record, across earlier records: one shipment for several orders of a customer). "same" needs the new entity to keep its
     *  pointer to the earlier record in its lines; where it sits above the lines a record can only ever belong to one earlier record.
     *  ask: further fields of the new record's line that are typed in the row, beside the quantity (a lot number, the quantity that passed). */
    public record Take(String entity, String from, List<String> statuses, Map<String, String> set, Map<String, String> lineSet, List<String> columns, String group, List<String> ask) {}
    /** Whether records of `target` can gather rows of several earlier records: its pointer to the earlier record (the limit's pair with "id") sits in its lines. */
    public static boolean combinable(Definition target, Limit limit) {
        for (int index = 0; index < limit.by().size(); index++)
            if (limit.entityBy().get(index).equals("id")) {
                String pointer = limit.by().get(index);
                return limit.lines() && target.lines() != null && target.lines().fields().stream().anyMatch(field -> field.name().equals(pointer));
            }
        return limit.lines();       // nothing points at the earlier record at all: rows are free to share a record
    }
    public static final List<String> PERIODS = List.of("all", "today", "week", "month", "year");
    /** Inside one record: left <op> right must hold on save (two dates or two numbers of the header, or of each line; right may be "today"). */
    public record Check(String left, String op, String right, boolean lines, String message) {}
    /** Across records: the sum of `field` over this entity's rows with the same `by` values may not exceed the sum of `entityField`
     *  over the other entity's rows with the matching `entityBy` values (shipped <= ordered, issued <= received). */
    public record Limit(String field, boolean lines, List<String> by, String entity, String entityField, boolean entityLines, List<String> entityBy,
                        List<String> ignore, List<String> entityIgnore, String message) {
        /** No quantities on either side: each earlier record (or line) is followed at most once. */
        public boolean once() { return counted() && (entityField == null || entityField.isEmpty()); }
        /** No quantity on this side: each record (or line) counts one - against the other side's number (seats, copies held) or, without one, once. */
        public boolean counted() { return field == null || field.isEmpty(); }
    }
    /** Something that follows by itself when a record is created (on = "create") or a status action is taken (on = its name):
     *  kind create - a record of another entity, its fields set from this one; kind act - a status action on the record a ref field points at. */
    public record EffectLines(Map<String, String> set) {}
    public record Make(String entity, Map<String, String> set, EffectLines lines) {}
    public record Act(String via, String action) {}
    /** Stored exactly as it is written (create | act), so what was saved reads back the same. */
    /** When what this record registers uses up an earlier record in full (by the limit this entity has against `entity`), that earlier record takes `action`:
     *  an order becomes 출하 완료 once the shipped quantities reach the ordered ones. */
    public record Fill(String entity, String action) {}
    /** parent: a field above the lines that points at a record (the item a BOM is of); child: a line field that points at the same kind of record (a part). */
    public record NoCycle(String parent, String child) {}
    /** show: balance (what is there per item and warehouse), lots (the lots, oldest first) or moves (every movement); all = the three as tabs. */
    /** thing: the entity whose quantities the view shows (the items, the equipment ...); none: everything the ledger holds. */
    public record LedgerView(String show, String thing) {
        public LedgerView(String show) { this(show, null); }
    }
    /** from / to: the date fields of the period (to empty = still valid); by: the fields whose records may not overlap in time (the item of a BOM). */
    public record Effective(String from, String to, List<String> by) {
        public boolean holds(JsonNode record, java.time.LocalDate day) {
            String start = record.hasNonNull(from) ? record.get(from).asString() : null, end = to != null && record.hasNonNull(to) ? record.get(to).asString() : null;
            return start != null && !java.time.LocalDate.parse(start).isAfter(day) && (end == null || !java.time.LocalDate.parse(end).isBefore(day));
        }
    }
    public static final List<String> LEDGER_VIEWS = List.of("all", "balance", "lots", "moves");
    /** The records of the screen move quantities in the ledger: in (each line makes a lot at its unit cost) or out (taken from the oldest lots, at their cost).
     *  item, quantity, warehouse, unitCost, date: the fields that say what, how much, where, at what cost and when (in the lines or above them).
     *  lot: a text field for the lot number of items kept by lot (a person's own number when receiving; which lot to take when issuing).
     *  move: the quantity goes from `place` to `toPlace`, each lot keeping its number, its cost and its age. */
    /** lotWhen: which things are kept by numbered lots - those whose record (of the item entity) has `field` in `is`; none said: any may be. */
    /** The quantity ledger: what a record moves - a thing (ref), how many, at a place (ref); in, out, moved to another place, or counted.
     *  lotWhen: which things are kept by numbered lots (none said: any may be). */
    public record Ledger(String direction, String thing, String quantity, String place, String unitCost, String date, String thingEntity, String placeEntity, String lot, String toPlace, LotWhen lotWhen) {}
    public record LotWhen(String field, List<String> is) {}
    /** A business record drawing on master data (업무단 using the layers): the master record(s) whose `match` fields equal this record's
     *  are found (the BOM of the item this work order makes), and for each of their lines a record of `into` is made - one item each.
     *  set: into field <- "<this record's field>" | "id" | "today" | "line.<master line field>" | "line.<a line-ref field>.<the field of the line it points at>"
     *  (one step through a layer-3 line: the part a requirement line points at in the BOM). quantity: into field <- the line's quantity × this record's.
     *  at: this record's date field the master must be valid on (when the master has an effective period); none = today. */
    public record Expand(String from, Map<String, String> match, String into, Map<String, String> set, String quantityInto, String quantityLine, String quantityTimes, String at) {}
    /** Down the flow: the records of `entity` that point at this one through `via` (the planned issues of a work order) take `action` too. */
    public record Cascade(String entity, String via, String action) {}
    /** A value found in master data: the record of `from` whose `match` fields equal this record's (and that is valid on `at`, when it has a
     *  period) gives `set` (this field <- its field). Several lookups for one field are tried in order (a customer's price, then the item's). */
    public record Lookup(String from, Map<String, String> match, String at, Map<String, String> set) {}
    /** A period lock: the group (named by the definition) and the date field a record is dated by. */
    public record Lock(String group, String date) {}
    public record CodeValue(String code, String name) {}
    /** A common-code group a definition declares (its fields choose from it): the units of measure, the kinds of a thing ... */
    public record CodeGroup(String code, String name, List<CodeValue> values) {}
    /** The groups the definition being read declares, so its fields may choose from them before they exist. */
    private final ThreadLocal<Map<String, List<String>>> declared = ThreadLocal.withInitial(LinkedHashMap::new);
    public record Effect(String on, Make create, Act act, Fill fill, Expand expand, Cascade cascade) {
        public Effect(String on, Make create, Act act) { this(on, create, act, null, null, null); }
        public Effect(String on, Make create, Act act, Fill fill) { this(on, create, act, fill, null, null); }
        public Effect(String on, Make create, Act act, Fill fill, Expand expand) { this(on, create, act, fill, expand, null); }
    }
    public static final List<String> COMPARISONS = List.of(">", ">=", "<", "<=", "==", "!=");
    /** A board of chart panels and nothing else. Each panel draws one summary screen's figures: chart = bar|line|pie, or figures (the headline numbers). */
    public record Panel(String summary, String chart, String value, String title, int width) {}
    public record Dashboard(List<Panel> panels) {}
    public static final List<String> PANEL_KINDS = List.of("bar", "line", "pie", "figures");
    public record Definition(String key, String type, String title, List<String> keywords, List<Field> fields, Lines lines, Status status, List<Rule> rules, Summary summary, Print print, Dashboard dashboard,
                             List<Check> checks, List<Limit> limits, List<Effect> effects, Over over,
                             /** period: what the list asks for when the screen opens (all | today | week | month | year). */
                             String period, Calendar calendar, Tree tree,
                             /** Further tables of lines beside `lines` (materials and steps of a work order), each kept in the record under its own name. */
                             List<LineSet> moreLines, Take take,
                             /** How the records of this screen move quantities in the ledger (null: they do not). */
                             Ledger ledger,
                             /** Master data that combines other master data (layer 2): field combinations no two records may share (one BOM per item),
                              *  and a parent that its own lines may not lead back to (no item inside its own BOM, at any depth). */
                             List<List<String>> uniqueBy, NoCycle noCycle,
                             /** A screen that shows the ledger (what is where, the lots, the movements) and stores nothing. */
                             LedgerView ledgerView,
                             /** Master data valid for a period (a BOM, a routing, a price from a date): records with the same `by` may not overlap. */
                             Effective effective,
                             /** A later stage of a flow: its records come only from the stage before (its take-over screen, or made by itself) - `follows`
                              *  names the field that points at that stage. Its own screen registers nothing new; a 기타 screen (a work screen with create)
                              *  registers ones without an earlier stage. */
                             String follows,
                             /** Data only: no screen of its own (no program, no menu) - its records are made and moved on by what happens elsewhere
                              *  (a work order's planned issues, expanded from the BOM); people read them through other screens, never change them directly. */
                             boolean dataOnly,
                             /** Values found in master data when a record is saved: the unit price of this customer and item valid on the order date. */
                             List<Lookup> lookups,
                             /** The period lock the records belong to: a month of `group` once locked takes no registration, change, deletion
                              *  or status action of a record dated (by `date`) in it. The group's name is the definition's word (수불, 근태 ...). */
                             Lock lock,
                             /** Common-code groups the definition brings: made when they are not there yet (one already there is used as it is). */
                             List<CodeGroup> codeGroups,
                             /** Spans that may not overlap: among records with the same `by` (statuses in `ignore` left out), from..to of one may not meet another's. */
                             List<NoOverlap> noOverlap,
                             /** Made from the records of an earlier entity, one each (a check-in from a visit request): what the framework
                              *  set up for it (the pointer, the once-limit, follows) and what its own screen takes over from the earlier list. */
                             From from,
                             /** What the screen is to the work, as the model judged it: master (기준 정보 - chosen from by the work) or work (업무 - records
                              *  that pile up day by day); null: not said (an older definition), read off its parts. */
                             String kind) {
        public Definition(String key, String type, String title, List<String> keywords, List<Field> fields, Lines lines, Status status, List<Rule> rules, Summary summary, Print print, Dashboard dashboard, List<Check> checks, List<Limit> limits, List<Effect> effects, Over over, String period, Calendar calendar, Tree tree, List<LineSet> moreLines, Take take, Ledger ledger, List<List<String>> uniqueBy, NoCycle noCycle, LedgerView ledgerView, Effective effective, String follows, boolean dataOnly, List<Lookup> lookups, Lock lock, List<CodeGroup> codeGroups, List<NoOverlap> noOverlap, From from) {
            this(key, type, title, keywords, fields, lines, status, rules, summary, print, dashboard, checks, limits, effects, over, period, calendar, tree, moreLines, take, ledger, uniqueBy, noCycle, ledgerView, effective, follows, dataOnly, lookups, lock, codeGroups, noOverlap, from, null);
        }
        /** The same definition, said to be master data or work. */
        public Definition withKind(String said) {
            return new Definition(key, type, title, keywords, fields, lines, status, rules, summary, print, dashboard, checks, limits, effects, over, period, calendar, tree, moreLines, take, ledger, uniqueBy, noCycle, ledgerView, effective, follows, dataOnly, lookups, lock, codeGroups, noOverlap, from, said);
        }
        public Definition(String key, String type, String title, List<String> keywords, List<Field> fields, Lines lines, Status status, List<Rule> rules, Summary summary, Print print, Dashboard dashboard,
                          List<Check> checks, List<Limit> limits, List<Effect> effects, Over over, String period, Calendar calendar, Tree tree) {
            this(key, type, title, keywords, fields, lines, status, rules, summary, print, dashboard, checks, limits, effects, over, period, calendar, tree, List.of(), null, null, List.of(), null, null, null, null, false, List.of(), null, List.of(), List.of(), null);
        }
        /** Every table of lines of the record: the first as "lines", then the further ones. */
        public List<LineSet> lineSets() {
            List<LineSet> out = new ArrayList<>();
            if (lines != null) out.add(new LineSet("lines", lines.label(), lines.fields(), lines.min(), lines.max()));
            if (moreLines != null) out.addAll(moreLines);
            return out;
        }
        public Field field(String name) { return fields.stream().filter(field -> field.name().equals(name)).findFirst().orElse(null); }
        public boolean document() { return lines != null; }
    }
    public record Stored(Definition definition, String programCode, String status, int revision) {}

    /** What the framework understands, with a guide for whoever writes definitions (the harness passes it on, it holds no copy). */
    public Map<String, Object> capabilities() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("parts", List.of(
                Map.of("part", "fields", "description", "화면의 항목들. 모든 화면에 있다"),
                Map.of("part", "serial 항목", "description", "저장할 때 자동으로 매겨지는 번호. 어느 화면에나 붙일 수 있다 (선택)"),
                Map.of("part", "lines", "description", "한 건 아래에 딸린 여러 줄의 표 (품목 줄, 작업 줄 ...). 어느 화면에나 붙일 수 있다 (선택). min, max 로 줄 수를 정할 수 있다"),
                Map.of("part", "moreLines", "description", "줄 표가 둘 이상 필요할 때 둘째부터의 줄 표 (작업지시의 투입 자재 표와 공정 표처럼). lines 가 있는 화면에만"),
                Map.of("part", "showWhen/requiredWhen/lockWhen", "description", "다른 항목의 값에 따라 항목이 보이거나, 필수가 되거나, 잠긴다 (항목마다 적는다)"),
                Map.of("part", "status", "description", "진행 상태와 상태를 바꾸는 버튼. 줄 표가 없어도 붙일 수 있다 (선택)"),
                Map.of("part", "rules", "description", "다른 자료와 얽힌 금지 규칙 (선택)"),
                Map.of("part", "checks", "description", "한 건 안에서 지켜야 할 비교 (종료일 >= 시작일, 출고 수량 <= 요청 수량 ...) (선택)"),
                Map.of("part", "limits", "description", "다른 자료를 넘지 못하는 한도: 이 자료의 합이 다른 자료의 합을 넘으면 저장을 거절한다 (출하 <= 수주, 출고 <= 입고 = 재고 부족 방지) (선택)"),
                Map.of("part", "effects", "description", "저절로 따라 일어나는 일: 등록하거나 상태 버튼을 누를 때 다른 자료를 만들거나, 가리키는 자료의 상태를 바꾼다 (선택)"),
                Map.of("part", "over", "description", "업무 화면: 이미 있는 자료를 다른 화면으로 연다 (승인 화면, 처리 대기 목록, 조회 전용 화면). 그 자료 중 정한 상태의 건만 보이고 정한 동작만 할 수 있다. 화면이 따로라서 권한도 따로 준다. fields 대신 over 만 적는다"),
                Map.of("part", "print", "description", "한 건을 종이 양식으로 출력 (수주서, 견적서 ...). 출력 버튼은 어느 화면에나 있고, 양식의 제목·결재란·맺음말, 회사 로고와 회사 정보, 받는 쪽 칸, 보일 항목, 부가세 줄을 정할 수 있다 (선택)"),
                Map.of("part", "period", "description", "목록을 처음 열 때 걸리는 기간 (all | today | week | month | year). 날짜 조회 조건은 언제나 '부터 ~ 까지'로 묻는다 (선택)"),
                Map.of("part", "calendar", "description", "달력 화면: 이미 있는 자료를 월 달력에 날짜별로 보여 준다 (납품 예정, 작업 일정, 휴가). fields 대신 calendar 만 적는다"),
                Map.of("part", "tree", "description", "트리 화면: 상위-하위가 있는 자료를 계층으로 보여 준다 (조직도, 분류 체계, BOM). fields 대신 tree 만 적는다"),
                Map.of("part", "from", "description", "앞 자료에서 이어 만드는 자료: \"from\": {\"entity\": \"<앞 자료 key>\", \"statuses\": [\"<가져올 앞 자료 상태 code>\"](선택)} 한 줄이면 앞 자료를 가리키는 항목·한 건에 한 번만·같은 이름 항목 넘겨받기가 갖춰진다 (선택)"),
                Map.of("part", "noOverlap", "description", "같은 대상(by)의 시간·기간(from~to)이 겹치는 자료를 거절한다 (예약, 대여, 일정) (선택)"),
                Map.of("part", "uniqueBy/noCycle", "description", "조합 기준 정보 (BOM, 공정처럼 다른 기준 정보를 조합한 마스터-디테일): 겹치면 안 되는 항목 조합(품목당 BOM 하나), 한 건 안에서 같은 줄 값 금지(줄 항목 unique), 자기 자신·순환 금지(하위가 다시 상위를 품지 못함)"),
                Map.of("part", "ledgerView", "description", "원장 보기 화면: 수량 원장의 현재 수량·묶음·들고 난 내역을 보여 준다 (저장하는 자료 없음). fields 대신 ledgerView 만 적는다"),
                Map.of("part", "effective", "description", "적용 기간: 적용 시작일·종료일이 있는 기준 정보 (같은 품목의 기간은 겹치지 않음). 펼치거나 고를 때 그날 유효한 것을 쓴다"),
                Map.of("part", "ledger", "description", "수량 원장: 이 화면의 자료가 무언가(thing)의 수량을 어느 위치(place)에서 들이고(in) 빼고(out) 옮기고(move) 센다(count). 묶음(LOT)별 단가, 먼저 들어온 것부터 꺼냄"),
                Map.of("part", "take", "description", "이어받기 화면: 앞 단계 자료(수주, 발주)에서 아직 남은 것을 목록으로 조회해, 줄을 고르고 수량만 고쳐 저장하면 다음 단계 자료(출하, 입고)가 만들어진다. 입력 폼이 없다. fields 대신 take 만 적는다"),
                Map.of("part", "dashboard", "description", "현황판: 표 없이 차트 패널만 놓는 화면. 패널마다 이미 있는 집계 화면 하나의 차트를 그린다. fields 대신 dashboard 만 적는다"),
                Map.of("part", "summary", "description", "집계 화면: 이미 있는 자료를 묶어서(월별, 거래처별 ...) 합계·건수 등을 표와 차트로 보여 준다. 자료를 저장하지 않으므로 fields 대신 summary 만 적는다")));
        out.put("fieldTypes", List.of(
                Map.of("type", "text", "description", "글자"),
                Map.of("type", "number", "description", "숫자. min, max 로 범위를, decimals 로 소수 자릿수(0~6, 0 이면 정수만)를 정할 수 있다. formula 로 같은 줄의 다른 숫자 항목에서 계산할 수 있고(+ - * / 괄호), 줄 표가 있으면 sum 으로 줄 항목의 합을 낼 수 있다"),
                Map.of("type", "date", "description", "날짜 (yyyy-MM-dd)"),
                Map.of("type", "time", "description", "시각 (HH:mm:ss). 출근 시각, 작업 시작 시각처럼 날짜 없이 시각만 적을 때"),
                Map.of("type", "yesno", "description", "예/아니오 (체크 칸). 사용 여부, 검사 완료 여부처럼 둘 중 하나일 때. 비워 두면 아니오다. required 를 주지 않는다"),
                Map.of("type", "memo", "description", "여러 줄의 긴 글 (비고, 특이 사항, 상세 설명). 줄 표의 항목으로는 못 쓴다"),
                Map.of("type", "code", "description", "공통 코드에서 고르는 값", "needs", "codeGroup"),
                Map.of("type", "ref", "description", "다른 자료에서 고르는 값 (그 자료의 id 를 저장). fill 로 고른 자료의 값을 다른 항목에 채울 수 있다", "needs", "ref.entity, ref.label"),
                Map.of("type", "user", "description", "등록한 사람 (로그인한 계정이 저절로 들어가고 고칠 수 없다: 신청자, 예약자, 청구자). 업무 화면 over 에 \"mine\": true 를 적으면 그 사람 자신의 자료만 보이고 다룬다"),
                Map.of("type", "serial", "description", "저장할 때 자동으로 매겨지는 번호 (머리 항목 전용)", "needs", "prefix (영문 대문자 1~6자)")));
        out.put("builtInRules", List.of(
                "필수 항목이 비면 저장을 거절한다 (400)",
                "min, max 를 벗어난 숫자, unique 인데 이미 있는 값, 줄 수가 lines.min~max 를 벗어난 저장을 거절한다 (400)",
                "ref 가 가리키는 자료가 없으면 저장을 거절한다 (400)",
                "다른 자료가 가리키고 있는 자료는 삭제를 거절한다 (409)",
                "formula, sum, serial 항목은 서버가 계산한다 (보낸 값은 무시)",
                "status.locked 상태의 자료는 수정·삭제를 거절한다 (409)",
                "등록자·등록일시·수정자·수정일시를 자동으로 기록한다",
                "모든 화면에 변경 이력이 있다: 등록·수정·상태 변경·삭제를 누가 언제 무엇에서 무엇으로 바꿨는지 자동으로 남기고 이력 버튼으로 본다 (따로 만들 필요 없다)",
                "목록은 자료가 많아도 일부씩 가져오고 전체 건수를 보여 준다 (따로 만들 필요 없다)",
                "화면 사이 이동이 내장되어 있다: 자료 한 건에서 그 자료를 쓰는 다른 화면의 자료로(수주 → 그 수주의 출하), 집계의 한 줄에서 그 내역 목록으로 넘어간다 (연결 버튼, 내역 버튼; 따로 만들 필요 없다)",
                "모든 화면의 자료 한 건마다 파일을 붙일 수 있다 (첨부 버튼; 견적서 PDF, 사진 등. 파일을 담을 항목을 따로 만들 필요 없다)"));
        out.put("ruleTypes", List.of(Map.of("type", "blockWhenReferenced",
                "description", "다른 자료(entity)의 줄들이 field 로 이 자료를 가리키고 있으면 action(delete, update 또는 status 의 action 이름)을 거절한다",
                "needs", "action, entity, field, message")));
        out.put("guide", GUIDE);
        out.put("limits", Map.of("fields", 30, "keyPattern", KEY, "fieldNamePattern", NAME));
        List<Map<String, Object>> entities = new ArrayList<>();
        for (Stored stored : all()) {
            Map<String, Object> entity = new LinkedHashMap<>();
            entity.put("key", stored.definition().key());
            entity.put("type", stored.definition().type());
            entity.put("title", stored.definition().title());
            entity.put("status", stored.status());
            entities.add(entity);
        }
        out.put("entities", entities);
        out.put("codeGroups", jdbc.queryForList("SELECT group_code AS \"code\", group_name AS \"name\" FROM sys_code_groups WHERE enabled ORDER BY group_code"));
        return out;
    }

    private static final String GUIDE = """
            정의(definition)의 모양 - 필요한 부품만 적는다:
            {"title": "<화면 이름>", "keywords": ["<찾을 때 칠 낱말>"],
             "kind": "master | work",                                      // 꼭 적는다: master = 기준 정보(업무가 골라 쓰는 바탕 자료: 사원, 품목, 거래처, 회의실),
                                                                           //   work = 업무(날마다 쌓이는 기록: 출퇴근, 주문, 신청, 점검 기록). 날짜 항목이 있다고 업무가 아니다(사원의 입사일)
             "fields": [<항목>...],                                        // 꼭 있어야 한다
             "lines": {"label": "<줄 표 이름>", "fields": [<항목>...], "min": 1, "max": <최대 줄 수>},   // 선택: 한 건에 여러 줄이 딸릴 때. min 기본 1, max 를 안 적으면 제한 없음
             "moreLines": [{"name": "<영문 name, 예: steps>", "label": "<줄 표 이름>", "fields": [<항목>...], "min": 0, "max": <최대 줄 수>}],   // 선택: 줄 표가 둘 이상일 때 둘째 표부터 여기에 (예: 작업지시의 '투입 자재' 는 lines, '공정' 은 moreLines). lines 가 있어야 한다. min 기본 0
             "status": {"initial": "<코드>", "values": [{"code": "OPEN", "label": "접수"}...],
                        "actions": [{"name": "confirm", "label": "확정", "from": ["OPEN"], "to": "CONFIRMED"}...], "locked": ["<수정·삭제를 막을 상태 코드>"], "closed": ["<끝난 상태 코드: 더 이어지지 않는다>"]},   // 선택: 진행 상태가 있을 때. 줄 표가 없어도 된다
             "rules": [{"type": "blockWhenReferenced", "action": "<delete|update|status 의 action 이름>", "entity": "<다른 자료 key>", "field": "<그 자료의 ref 항목 name (위쪽 또는 줄 표)>", "message": "<거절 안내>"}]}   // 선택
            항목의 모양: {"name": "<camelCase 영문>", "label": "<한국어 이름>", "type": "text|number|date|time|yesno|memo|code|ref|serial", "required": true|false, "search": true|false}
              더 적을 수 있는 것: code 는 "codeGroup", ref 는 "ref": {"entity", "label"}, serial 은 "prefix" 가 꼭 필요하다.
              "min", "max": 숫자 항목의 허용 범위. "decimals": 숫자 항목의 소수 자릿수 (0 = 정수만, 2 = 둘째 자리까지. 안 적으면 입력한 대로). "unique": true 는 같은 값이 두 번 저장되지 않게 한다 (줄 항목에는 못 쓴다).
              "formula": 같은 줄(또는 같은 머리)의 숫자 항목으로 계산, 예 "quantity * unitPrice". "sum": 줄 표의 숫자 항목을 더한 값, 예 "amount" (줄 표가 있을 때만).
              "pick": 고르는 방식은 둘뿐이다. "dropdown"(목록에서 고름) 과 "search"(검색창: 코드나 이름을 치면 후보가 뜨고, 돋보기·F2 로 여러 열의 보조 검색창이 열린다).
                      안 적으면 code 는 dropdown, ref 는 search 다 (ref 는 그대로 두면 검색창이므로 보통 적을 필요가 없다). 보조 검색창에 보일 열은 "ref": {"entity", "label", "columns": ["<그 자료의 항목 name>", ...]} 로 정할 수 있다.
              고른 자료는 어디서나 "코드 이름"으로 보인다 (예: V-001 한빛상사). 이름은 ref.label, 코드는 그 자료의 첫 항목이다. 다른 항목을 코드로 쓰려면 "ref": {..., "code": "<항목 name>"}.
              "fill": ref 항목에서 자료를 고르면 그 자료의 값을 다른 항목에 채운다, 예 {"unitPrice": "<고른 자료의 항목 name>"}.
              조건에 따라 달라지는 항목: "showWhen" | "requiredWhen" | "lockWhen": {"field": "<같은 표의 다른 항목 name (줄 항목은 위쪽 항목도 됨)>", "is": ["<값>", ...]}
                showWhen: 그 값일 때만 보인다 (아닐 때는 비워지고 필수도 묻지 않는다). requiredWhen: 그 값일 때만 필수다 (이때 required 는 적지 않는다). lockWhen: 그 값일 때는 고칠 수 없다.
                is 에는 저장되는 값을 적는다: code 항목은 코드(코드 이름이 아니다), yesno 는 "true" 또는 "false", 비어 있음은 "".
                "is" 대신 "isNot" 을 쓰면 그 값이 아닐 때 성립한다. 예) 다른 항목을 고르면 그 값으로 채워지고 고칠 수 없게: 고르는 항목에 fill, 채워지는 항목에 "lockWhen": {"field": "<고르는 항목>", "isNot": [""]} (골랐으면 잠김)
                예) 구분이 외주(OUT)일 때만 외주처가 보이고 필수: {"name": "vendorId", "label": "외주처", "type": "ref", ..., "showWhen": {"field": "kind", "is": ["OUT"]}, "requiredWhen": {"field": "kind", "is": ["OUT"]}}
              다른 줄 표(moreLines)의 숫자를 더한 머리 합계는 "sum": "<줄 표 name>.<항목 name>" 으로 적는다.
            적어도 하나의 항목은 required 이거나 serial 이어야 한다. formula, sum, serial 항목에는 required 를 주지 않는다.
            한 건 안의 비교: "checks": [{"left": "<항목 name>", "op": ">|>=|<|<=|==|!=", "right": "<항목 name 또는 today>", "lines": true|false, "message": "<어겼을 때 안내>"}]
              날짜끼리, 시각끼리 또는 숫자끼리. lines true 면 줄마다 그 줄의 항목끼리 견준다. 예: 종료일이 시작일보다 빠를 수 없다 = {"left": "endDate", "op": ">=", "right": "startDate", ...}
            한도 (다른 자료를 넘지 못함): "limits": [{"field": "<이 자료의 숫자 항목>", "lines": true|false, "by": ["<이 자료의 항목>", ...],
                                                     "entity": "<한도가 되는 자료 key>", "entityField": "<그 자료의 숫자 항목>", "entityLines": true|false, "entityBy": ["<그 자료의 항목 또는 id>", ...], "message": "<넘었을 때 안내>"}]
              by 와 entityBy 는 같은 순서로 짝을 짓는다. 이 자료에서 by 가 같은 것끼리 field 를 모두 더한 값이, entity 에서 entityBy 가 같은 것끼리 entityField 를 더한 값을 넘으면 저장이 거절된다.
              예) 출하 수량이 수주 수량을 넘지 못함: 출하의 limits = {"field": "quantity", "lines": true, "by": ["orderId", "itemId"], "entity": "sales_order", "entityField": "quantity", "entityLines": true, "entityBy": ["id", "itemId"], ...}
                  (출하의 orderId 는 수주를 가리키는 ref 이므로 수주의 id 와 짝이 된다.) 재고 부족 방지 = 출고 수량 합 <= 입고 수량 합 (by 품목 ↔ entityBy 품목).
              취소된 건을 세지 않으려면 "ignore": ["<이 자료의 상태 코드>"], "entityIgnore": ["<그 자료의 상태 코드>"].
              건수로 셀 때 (정원·보유 수량만큼만: 교육 정원, 책 권수): field 를 적지 않고 entityField 에 그쪽 숫자 항목을 적는다 - 이 자료 한 건이 1로 세어진다.
                반납·취소처럼 끝난 건은 "ignore" 에 그 상태 code 를 적으면 세지 않는다 (돌려받으면 다시 빌릴 수 있다).
              수량 없이 앞 자료 한 건에 한 번만 이어질 때 (민원 하나에 처리 지시 하나, 신청 하나에 심사 하나): field 와 entityField 를 적지 않는다 -
                {"by": ["<앞 자료를 가리키는 ref 항목>"], "entity": "<앞 자료 key>", "entityBy": ["id"], "message": "..."}. 이어받기 화면에서는 수량 칸 없이 고르기만 한다.
                앞 자료에 "처리됨" 같은 상태를 따로 두지 않는다: 이미 이어진 것은 이 한도가 안다.
            따라 일어나는 일: "effects": [{"on": "create | <status action name>", "create": {"entity": "<만들 자료 key>", "set": {"<만들 자료의 항목>": "<이 자료의 항목 | id | today>"}, "lines": {"set": {"<만들 자료의 줄 항목>": "<이 자료의 줄 항목>"}}}},
                                         {"on": "create | <action name>", "act": {"via": "<이 자료의 ref 항목>", "action": "<그 ref 가 가리키는 자료의 action name>"}}]
              create: 다른 자료 한 건을 만든다 (만들 자료의 필수 항목은 모두 set 에 있어야 한다. lines 를 적으면 이 자료의 줄마다 한 줄씩 만든다). 예: 수주를 확정하면 출하가 만들어진다.
              act: 가리키는 자료의 상태 버튼을 대신 누른다. 예: 출하를 등록하면 그 수주가 '출하됨'이 된다 (수주에 그 action 이 있어야 한다).
              기준 정보 펼치기 (업무가 기준 정보를 쓰는 길): {"on": "create | <action name>", "expand": {"from": "<줄 표가 있는 기준 정보 key, 예: bom>", "match": {"<그 기준 정보의 위쪽 항목, 예: itemId>": "<이 자료의 항목, 예: itemId>"},
                  "into": "<만들 자료 key, 예: 자재 소요>", "set": {"<만들 자료의 항목>": "<이 자료의 항목 | id | today | line.<기준 정보 줄 항목> | line.<줄을 가리키는 항목>.<그 줄의 항목>>"},
                  "quantity": {"into": "<만들 자료의 수량 항목>", "line": "<기준 정보 줄의 수량 항목>", "times": "<이 자료의 수량 항목>"}}}
                이 자료와 match 가 같은 기준 정보를 찾아, 그 줄마다(줄 표가 없는 기준 정보면 맞는 건마다: 한 건에 한 쌍인 BOM) 만들 자료를 한 건씩(한 건 한 품목) 만든다. line.<항목> 은 그 줄(또는 그 건)의 항목이다. 수량 = 줄의 수량 × 이 자료의 수량. 맞는 기준 정보가 없으면 저장이 거절된다.
                예) 작업지시를 등록하면 그 품목 BOM 대로 자재 소요가 생김: {"on": "create", "expand": {"from": "bom", "match": {"itemId": "itemId"}, "into": "work_order_material",
                    "set": {"workOrderId": "id", "itemId": "line.componentId"}, "quantity": {"into": "quantity", "line": "quantity", "times": "quantity"}}}
                3레이어(공정별 자재소요량)를 펼칠 때 자재는 BOM 줄을 가리키므로 "line.componentId.componentId" 처럼 한 번 더 따라간다.
              다 차면 상태 바꾸기: {"on": "create", "fill": {"entity": "<한도가 되는 앞 단계 자료 key>", "action": "<그 자료의 action name>"}}
              아래로 전파: {"on": "<이 자료의 action name>", "cascade": {"entity": "<이 자료를 가리키는 다음 단계 자료 key>", "via": "<그 자료에서 이 자료를 가리키는 ref 항목>", "action": "<그 자료의 action name>"}}
                - 이 자료가 그 동작을 하면 이 자료를 가리키는 그 자료들 중 그 동작을 할 수 있는 상태인 것도 그 동작을 한다 (작업지시를 마감하면 그 출고 예정도 마감, 마감취소하면 다시 연다).
              끝난 상태(status.closed): 지시가 마감·취소·완료되어 더 이어지지 않는 상태. 끝난 자료는 이어받기 목록에서 빠지고, 그것을 한도로 가리키는 다음 단계 자료를 새로 등록할 수 없다.
                잠금(locked)과 다르다: 확정처럼 잠가도 다음 단계는 이어지는 상태는 locked 에만, 마감·취소·완료처럼 끝난 상태는 closed 에(대개 locked 에도) 넣는다.
            기준 정보에서 찾아 채우기 (선택): "lookups": [{"from": "<기준 정보 key>", "match": {"<그 자료의 항목>": "<이 자료의 항목>", ...}, "at": "<이 자료의 날짜 항목>", "set": {"<이 자료의 항목>": "<그 자료의 항목>"}}]
              // 저장할 때 비어 있는 칸을, match 가 같고 at 날짜에 유효한(적용 기간이 있으면) 기준 정보 한 건의 값으로 채운다 (거래처·품목별 단가 → 수주 단가). 화면에서도 고르는 즉시 채워진다.
              // 같은 칸에 여러 개를 적으면 적은 순서대로 먼저 찾은 값을 쓴다 (거래처 단가 → 없으면 품목 기본 단가). 직접 적은 값은 그대로 둔다. 필수 칸인데 찾지 못하면 저장이 거절된다.
            화면 없는 데이터 (선택): "screen": false   // 다른 업무가 저절로 만들고 바꾸기만 하는 자료(작업지시를 등록하면 BOM 에서 생기는 출고 예정 ...). 프로그램·메뉴가 없고 사람이 직접 등록·수정하지 않는다. 다른 화면에서 고르거나 이어받기 목록으로 읽는다.
            후행 자료 (선택, 흐름의 두 번째 단계부터):
              "follows": "<앞 단계 자료를 가리키는 ref 항목 name>"   // 이 자료는 앞 단계를 이어받아서만 생긴다(이어받기 화면, 자동 처리). 자기 화면에서는 신규 등록이 없다.
                - 그 ref 항목은 required 로 두지 않는다. 앞 단계 없이 따로 등록해야 하면 기타 화면을 만든다: over {"entity": "<이 자료 key>", "create": true}, title "기타 <이름>" (예: 기타 출하지시). 기타 화면에서는 앞 단계 항목이 비어 있다.
                이 자료를 등록해서 앞 단계 자료의 수량이 모두 채워지면(남은 것이 없으면) 그 자료의 상태 버튼을 대신 누른다. 예: 출하실적이 수주 수량을 다 채우면 수주가 '출하 완료'가 된다.
                이 자료에 그 앞 단계를 한도로 하는 limits (entityBy 에 id) 가 있어야 한다.
              따라 만든 자료도 그 자료의 규칙을 그대로 따른다. 거절되면 원래 동작도 함께 취소된다.
            출력 양식: 한 건을 종이로 뽑을 때의 제목·결재란·맺음말. 안 적어도 출력은 된다 (제목은 화면 이름, 결재란은 담당·검토·승인).
              "print": {"title": "<양식 제목, 예: 견 적 서>", "signers": ["담당", "팀장", "대표"], "note": "<맨 아래 한두 줄, 예: 위와 같이 견적합니다.>",
                        "logo": true, "company": true,            // 회사 로고 / 우리 회사 정보 칸(상호, 대표, 사업자번호, 주소, 전화 - 시스템 설정에 적어 둔 것)
                        "receiver": "<받는 쪽을 고르는 ref 항목 name, 예: 거래처 항목>",   // 공급받는자 칸에 그 자료의 이름이 들어간다
                        "fields": ["<양식에 보일 위쪽 항목 name>", ...], "columns": ["<양식에 보일 줄 항목 name>", ...],   // 안 적으면 전부
                        "vat": 10}                                // 줄 합계 아래에 공급가액·부가세(10%)·합계 줄 (줄 합계 항목이 있는 화면만)
            수량 원장 (등록·업무 화면, 선택): 이 화면의 자료가 무언가(thing)의 수량을 어느 위치(place)에서 들이고, 빼고, 옮기고, 센다.
              (예: 자재 입고·출고 → thing=품목, place=창고 / 장비 대여·반납 → thing=장비, place=보관 장소 / 좌석 배정 → thing=좌석 종류, place=강의실)
              "ledger": {"direction": "in" | "out" | "move" | "count", "thing": "<대상 ref 항목 name>", "quantity": "<수량 항목 name>", "place": "<위치 ref 항목 name (필수 항목)>",
                         "unitCost": "<단가 항목 name (in·count 일 때만, 선택)>", "date": "<기준 날짜 항목 name (안 적으면 첫 필수 날짜)>",
                         "lot": "<묶음 번호(LOT 등)를 적는 text 항목 name (선택)>", "toPlace": "<받는 위치 ref 항목 name (move 일 때만)>"}
              in: 줄마다 묶음 하나가 생기고 그 줄의 단가가 그 묶음의 단가가 된다. out: 그 위치의 먼저 들어온 묶음부터 꺼내고, 남은 수량이 모자라면 저장이 거절된다.
                (그래서 "재고보다 많이 못 나간다"에는 limits 를 적지 않는다 - out 이 이미 막는다. 들어온 자료를 한도로 삼는 limits 는 무시된다.)
              move: place 에서 toPlace 로 옮긴다 (같은 위치 자료를 가리키는 다른 필수 ref). 묶음 번호와 단가는 그대로 따라간다. unitCost 는 적지 않는다.
              count: quantity 는 센 수량이다: 그 위치(와 묶음 번호를 적었으면 그 묶음)의 장부 수량이 센 수량으로 맞춰진다. 늘어난 만큼은 새 묶음, 줄어든 만큼은 먼저 들어온 묶음부터 뺀다. 처음 넣는 수량도 count 로 넣는다.
              꺼낸 묶음의 단가로 나간 것의 원가가 저절로 정해진다.
              묶음 번호로 관리하는 것: "lotWhen": {"field": "<thing 이 가리키는 자료의 항목>", "is": ["<그 값이면 묶음 번호로 관리>"]} 를 ledger 에 적는다
                (예: 품목 화면의 관리 방식 code 항목이 LOT 이면). 안 적으면 무엇이든 묶음 번호를 적을 수 있다.
                묶음 번호로 관리하는 것은 ledger.lot 항목에 번호를 적을 수 있다: in 에서는 그 번호가 묶음 번호가 되고(안 적으면 자동 번호), out 에서는 적은 묶음에서만 꺼낸다.
                묶음 번호로 관리하지 않는 것에 번호를 적으면 저장이 거절된다. ledger.lot 항목은 필수로 두지 않고 showWhen·requiredWhen 도 달지 않는다 (어느 것이 묶음 번호로 관리되는지는 lotWhen 이 정한다).
              원장 보기 화면 - fields 없이 ledgerView 만 적는다: {"title": "<화면 이름, 예: 재고 현황, 장비 보관 현황>", "ledgerView": {"show": "all | balance | lots | moves", "thing": "<보여 줄 대상 자료 key, 예: item, equipment>"}}
                남은 수량·현재 수량을 보는 화면은 집계(summary)로 들어온 것 − 나간 것을 계산하지 말고 원장 보기로 한다 (원장이 이미 남은 수량을 안다). thing 을 적으면 그 대상만 보인다.
                (balance = 현재 수량·현재고·남은 수량, lots = 묶음(LOT)별 수량, moves = 들고 난 내역(입출고 내역, 반입·대여 내역, 수불 내역), all = 셋을 탭으로.
                 요청이 현재 수량과 내역을 함께 말하면 all 이다)
            줄을 가리키는 항목 (3레이어: 조합 기준 정보끼리 다시 묶는 기준 정보. 예: 공정별 자재소요량 = 품목 + 줄마다 [그 품목 공정의 한 단계, 그 품목 BOM 의 자재 한 줄, 소요량]):
              {"name": "stepId", "label": "공정", "type": "ref", "ref": {"entity": "<줄 표가 있는 기준 정보 key>", "label": "<그 줄 표의 항목 name>", "line": true,
                                                                          "within": {"field": "<이 자료의 항목, 예: itemId>", "target": "<그 기준 정보의 위쪽 항목, 예: itemId>"}}}
              line true: 그 자료 한 건이 아니라 그 자료의 줄 한 줄을 고른다. within: 그 줄이 속한 건의 target 이 이 자료의 field 와 같은 것만 고를 수 있다 (같은 품목의 공정·BOM 만).
            조합 기준 정보 (다른 기준 정보를 묶는 기준 정보: BOM = 상위 품목·하위 자재·소요량 한 쌍이 한 건, 공정 = 품목 + 공정 순서 줄. 업무보다 먼저 등록해 둔다):
              "uniqueBy": [["<위쪽 항목>", ...]]   // 이 조합이 같은 자료는 둘일 수 없다. 예: 품목당 BOM 하나 = [["itemId"]], 품목·버전마다 하나 = [["itemId", "version"]]
              줄 항목에 "unique": true   // 한 건의 줄 안에서 같은 값을 두 번 넣지 못한다. 예: 한 BOM 에 같은 하위 자재를 두 줄로 넣지 못함
              "noCycle": {"parent": "<상위를 가리키는 ref 항목>", "child": "<하위를 가리키는 ref 항목 (같은 자료를 가리킴, 같은 건의 항목이거나 줄 항목)>"}   // 하위가 상위 자신이거나, 다른 건을 거쳐 다시 상위로 돌아오면 거절 (BOM 순환 방지)
              BOM 을 쌍으로: {"fields": [상위 품목(ref item), 하위 자재(ref item), 소요량], "uniqueBy": [["parentItemId", "childItemId"]] 또는 적용 기간 by [상위, 하위], "noCycle": {"parent": "parentItemId", "child": "childItemId"}}
            적용 기간 (기간마다 바뀌는 기준 정보: BOM, 공정, 단가 ...): "effective": {"from": "<적용 시작일 date 항목 (필수 항목)>", "to": "<적용 종료일 date 항목 (비우면 계속 적용)>", "by": ["<기간이 겹치면 안 되는 기준 항목, 예: itemId>"]}
              by 가 같은 자료끼리 기간이 겹치면 거절, 종료일이 시작일보다 앞서도 거절. 기간이 있는 기준 정보는 uniqueBy(하나만) 대신 effective 를 쓴다.
              이 기준 정보를 펼치는 업무 자료는 expand 에 "at": "<업무 자료의 날짜 항목, 예: workDate>" 를 적으면 그날 유효한 것을 쓴다 (안 적으면 오늘).
            앞 자료에서 이어 만드는 자료 (방문 신청 → 방문 확인, 대출 → 반납, 지원 → 면접처럼 앞 자료 한 건마다 하나): "from": {"entity": "<앞 자료 key>", "statuses": ["<가져올 앞 자료의 상태 code>"](선택)}
              앞 자료를 가리키는 ref 항목, 앞 자료 한 건에 한 번만 이어지는 한도, follows 가 저절로 붙는다 (따로 적지 않는다). 앞 자료와 같은 name·같은 type 의 항목은 그 값을 넘겨받고,
              나머지 항목(글자·숫자·날짜·시각·예/아니오)은 이어받기 목록의 줄에서 적는다.
            겹침 금지 (같은 대상의 시간·기간이 겹치면 안 될 때: 회의실 예약, 장비 대여, 휴가): "noOverlap": [{"from": "<시작 항목>", "to": "<끝 항목>", "by": ["<같으면 겹치면 안 되는 항목>"], "ignore": ["<세지 않을 상태 code, 예: 취소>"], "message": "<겹칠 때 안내>"}]
              from·to 는 둘 다 필수인 date 항목이거나 time 항목이다. time 이면 그 날짜 항목을 by 에 넣는다 (같은 날끼리만 견준다). time 은 끝과 시작이 맞닿아도 된다 (10:00~11:00, 11:00~12:00). 끝이 시작보다 앞서도 거절된다.
            조회 (등록·업무 화면, 선택):
              "period": "month"      // 목록을 처음 열 때의 기간: all | today | week | month | year. 날짜 조회 조건은 언제나 '부터 ~ 까지'다
            공통 코드 그룹 선언 (선택): "codeGroups": [{"code": "<영문 대문자, 예: UNIT>", "name": "<그룹 이름, 예: 단위>", "values": [{"code": "<코드, 예: EA>", "name": "<이름, 예: 개>"}, ...]}]
              // code 항목이 고를 그룹이 아직 없으면 여기에 선언한다 (저장할 때 없으면 만들어지고, 이미 있으면 그대로 쓴다). 있는 그룹은 선언하지 않고 codeGroup 으로 바로 쓴다.
            기간 마감 (선택): "lock": {"group": "<마감 묶음 이름, 예: 수불, 근태, 정산>", "date": "<이 자료의 날짜 항목>"}
              // 같은 묶음의 화면들은 달 단위로 함께 마감된다. 마감된 달의 날짜인 자료는 등록·수정·삭제·상태 처리가 막힌다. 묶음 안에 ledger 화면이 있으면 그 달까지 수량 원장도 잠기고 기말 수량이 남는다.
              // 요청이 마감을 말할 때만 적는다. 기준 정보에는 적지 않는다.
            달력 화면의 모양 - fields 없이 calendar 만 적는다 (자료는 그 등록 화면에서 넣는다):
            {"title": "<화면 이름, 예: 납품 일정>", "keywords": [...],
             "calendar": {"entity": "<자료 key>", "date": "<날짜 항목 name>", "end": "<끝 날짜 항목 name (기간일 때만)>", "label": "<칸에 보일 항목 name (안 적으면 첫 항목)>"}}
            이어받기 화면의 모양 - fields 없이 take 만 적는다 (여러 건을 목록에서 한꺼번에 다음 단계로 넘기는 화면. 예: 수주를 조회해 출하 등록, 발주를 조회해 입고 등록):
            {"title": "<화면 이름, 예: 수주 기준 출하 등록>", "keywords": [...],
             "take": {"entity": "<만들 자료 key, 예: shipment>", "from": "<앞 단계 자료 key, 예: sales_order>",
                      "statuses": ["<목록에 보일 앞 단계 상태 코드>", ...],                 // 선택: 안 적으면 모든 상태
                      "set": {"<만들 자료의 위쪽 항목>": "<앞 단계의 위쪽 항목 | id | today>"},   // 선택: 함께 넘길 값 (예: 거래처)
                      "lines": {"set": {"<만들 자료의 줄 항목>": "<앞 단계의 줄 항목>"},           // 선택: 줄마다 함께 넘길 값 (예: 단가)
                                "ask": ["<만들 자료의 줄 항목>", ...]},                             // 선택: 목록의 줄에서 수량과 함께 직접 적을 항목 (예: LOT 번호, 합격 수량, 나간 시각, 반납 여부). 글자·숫자·날짜·시각·예/아니오 항목
                      "group": "source"}}   // 선택: 고른 줄을 묶는 기본 방식. source = 앞 단계 한 건마다 한 건(기본), same = 위쪽 값(거래처 등)이 같은 줄끼리 한 건 (여러 수주를 출하 한 건으로)
              same 은 만들 자료가 앞 단계를 가리키는 ref 항목을 줄 표에 둘 때만 된다 (위쪽에 두면 한 건은 앞 단계 한 건에만 속한다). 될 때는 화면에서 그때그때 둘 중 고를 수 있다.
              만들 자료가 아직 없으면 steps 로 먼저 그 자료를 만든다 (앞 단계를 가리키는 ref, follows, 앞 단계를 한도로 하는 limits) - 앞 단계 화면은 고치지 않는다.
              만들 자료의 등록 화면에 앞 단계를 한도로 하는 limits 가 있어야 한다 (그 한도의 by ↔ entityBy 로 짝이 지어지고, 한도 - 이미 처리한 양 = 남은 양이 목록에 나온다).
              만들 자료가 줄 표 없이 한 건에 한 품목을 담는 자료면(프로세스 단계의 기본 모양) lines 대신: "set" 의 값에 앞 단계의 줄 항목도 쓸 수 있고(예: 단가),
                목록의 줄에서 직접 적을 항목은 "ask": ["<만들 자료의 항목>", ...] 로 적는다 (예: LOT 번호). 고른 줄 하나가 자료 한 건이 된다.
              한도의 by 에 있는 항목(앞 단계를 가리키는 ref, 품목)과 수량은 저절로 채워지므로 set 에 적지 않는다. 남은 필수 위쪽 항목(출하일, 창고)은 화면에서 한 번 입력한다.
            트리 화면의 모양 - fields 없이 tree 만 적는다:
            {"title": "<화면 이름, 예: 조직도>", "keywords": [...],
             "tree": {"entity": "<자료 key>", "parent": "<상위를 고르는 ref 항목 name>", "label": "<줄에 보일 항목 name>", "columns": ["<옆에 보일 항목 name>", ...]}}
              같은 자료 안의 상위-하위(상위 부서, 상위 분류)는 parent 만 적는다. 그 등록 화면에 같은 자료를 가리키는 ref 항목이 있어야 한다.
              다른 자료 두 건을 잇는 구조(BOM: 상위 품목 - 하위 품목 - 소요량)는 "child": "<하위를 고르는 ref 항목 name>" 도 적는다. 나무는 그 두 항목이 가리키는 자료(품목)로 그려진다.
            집계 화면(현황, 합계, 통계, 차트)의 모양 - fields 없이 summary 만 적는다:
            {"title": "<화면 이름>", "keywords": [...],
             "summary": {"entity": "<모을 자료 key>", "lines": true|false,      // lines true: 그 자료의 줄 표를 한 줄씩 모은다 (품목별처럼 줄 항목으로 묶거나 줄의 숫자를 더할 때)
                         "groupBy": [{"field": "<항목 name 또는 status>", "by": "day|month|year"}],   // 1~2개. by 는 날짜 항목일 때만 (안 적으면 month)
                         "values": [{"label": "<열 이름>", "op": "sum|count|avg|min|max", "field": "<숫자 항목 name>"}],   // count 는 field 없이
                         "filters": ["<조회 조건으로 쓸 위쪽 항목 name 또는 status>"],   // 날짜는 기간으로 조회된다. 안 적으면 날짜·묶는 기준·상태가 자동으로 조회 조건이 된다
                         "chart": {"type": "bar|line|pie", "value": "<values 의 label>"}}}   // 선택
              lines 가 false 면 values 에는 위쪽 숫자 항목을, true 면 줄 표의 숫자 항목을 쓴다.
            집계 화면에 더할 수 있는 분석 틀 (summary 안에 적는다, 모두 선택):
              계획 대비 실적: "compare": {"type": "plan", "entity": "<계획 자료 key>", "field": "<계획 숫자 항목>", "groupBy": ["<계획 자료의 항목 name>", ...], "value": "<견줄 values 의 label>", "label": "계획"}
                  compare.groupBy 는 summary.groupBy 와 같은 순서로, 계획 자료에서 같은 뜻인 항목을 적는다 (월 ↔ 계획의 날짜 항목, 거래처 ↔ 계획의 거래처 항목). 계획·차이·달성률(%) 열이 붙는다.
                  계획을 담은 자료가 아직 없으면 먼저 그 등록 화면을 만들어야 한다.
              전기 대비: "compare": {"type": "previous", "by": "month" | "year", "value": "<values 의 label>"}   // 전월 / 전년 같은 때의 값, 증감, 증감률(%) 열이 붙는다. 첫 groupBy 가 날짜(month 나 year)여야 한다
              잔량·재고 (다른 자료를 뺀 나머지): "compare": {"type": "minus", "entity": "<빼는 자료 key>", "lines": true|false, "field": "<빼는 숫자 항목>", "groupBy": [...], "value": "<values 의 label>", "label": "<빼는 값의 열 이름, 예: 출하 수량>", "balance": "<나머지의 열 이름, 예: 수주 잔량, 재고>"}
                  예) 수주 잔량 = 수주 수량 − 출하 수량, 미입고 = 발주 수량 − 입고 수량, 재고 = 입고 수량 − 출고 수량. compare.groupBy 는 계획 대비와 같은 규칙으로 맞춘다 (품목 ↔ 품목).
                  자료 한 건씩 보려면 summary.groupBy 에 {"field": "id"} 를 쓰고, compare.groupBy 에는 그 자료를 가리키는 ref 항목을 적는다 (수주 한 건 ↔ 출하의 수주 항목).
              처리 일수: values 에 {"label": "평균 처리 일수", "op": "avg", "between": ["<시작 날짜 항목>", "<끝 날짜 항목>"]}   // 두 날짜 사이의 일수. 끝 날짜가 빈 건은 빼고 계산한다
              누계: "cumulative": true   // 첫 번째 values 를 위에서부터 더해 가는 누계 열
              구성비: "share": true   // 각 줄이 전체에서 차지하는 비율(%) 열
              순위: "top": 10        // 첫 번째 values 가 큰 순서로 그만큼만
            업무 화면(승인·처리·조회 전용)의 모양 - 자료는 그대로 두고 화면만 하나 더 만든다. fields 없이 over 만 적는다:
            {"title": "<화면 이름, 예: 수주 승인>", "keywords": [...],
             "over": {"entity": "<자료 key>", "statuses": ["<보여 줄 상태 코드>", ...], "actions": ["<이 화면에서 할 동작 name>", ...], "edit": true|false, "create": true|false, "mine": true|false}}
              mine: true 면 그 자료의 user 항목(등록한 사람)이 로그인한 사람인 건만 보이고 다룬다 ("내 예약", "내 신청" 화면).
              ask: {"<동작 name>": ["<그 자료의 항목 name>", ...]} - 그 동작을 할 때 목록의 줄마다 그 항목만 적게 한다 (거절 사유, 나간 시각, 담당자). 다른 항목은 고치지 않는다.
                한 건에 한 번 끝나는 뒷일(퇴실, 반납, 확인, 전달)은 새 자료를 만들지 말고, 그 자료에 항목과 상태·동작을 두고 이 업무 화면의 동작 + ask 로 한다.
              statuses 를 적으면 그 상태의 건만 보인다 (승인 대기 = 아직 승인 전 상태). 안 적으면 전부 보인다. actions 의 동작만 버튼으로 나온다. edit false(기본)면 내용은 못 고친다. create 가 없으면 새로 등록할 수 없고, 지우는 것은 언제나 안 된다.
              create true 면 이 화면에서 새로 등록할 수 있다 (등록만 하는 화면: statuses·actions 를 비우고 edit false, create true - 고치기·취소·마감은 그 자료의 관리 화면에서).
              권한은 화면 단위다: 누가 승인하는지는 이 화면을 어느 역할에 주느냐로 정해진다 (사람이 권한 화면에서 준다).
              등록 화면에서는 못 하고 업무 화면에서만 하게 하려면, 그 자료의 등록 화면 정의에서 그 동작에 "separate": true 를 붙인다: {"name": "approve", ..., "separate": true}.
            현황판(대시보드)의 모양 - 차트 패널만 있다. fields 없이 dashboard 만 적는다:
            {"title": "<화면 이름>", "keywords": [...],
             "dashboard": {"panels": [{"summary": "<이미 있는 집계 화면 key>", "chart": "bar|line|pie|figures", "value": "<그 집계 화면의 values label>", "title": "<패널 제목>", "width": 1|2|3}]}}
              패널은 이미 있는 집계 화면만 가리킬 수 있다. chart figures 는 차트 대신 그 집계의 핵심 숫자(합계, 달성률 등)를 보여 준다. width 는 한 줄 3칸 중 몇 칸을 쓸지 (기본 1).
              chart, value, title 을 안 적으면 그 집계 화면의 것을 쓴다.
            여기 없는 낱말은 쓸 수 없다. 적어도 동작하지 않으므로 거절된다.
            """;

    public Stored find(String key) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT definition, program_code, status, revision FROM app_definitions WHERE entity_key = ?", key);
        if (rows.isEmpty()) return null;
        Map<String, Object> row = rows.get(0);
        return new Stored(parse(key, mapper.readTree((String) row.get("definition")), false), (String) row.get("program_code"),
                (String) row.get("status"), ((Number) row.get("revision")).intValue());
    }

    public List<Stored> all() {
        List<Stored> out = new ArrayList<>();
        for (String key : jdbc.queryForList("SELECT entity_key FROM app_definitions ORDER BY entity_key", String.class)) out.add(find(key));
        return out;
    }

    public String json(Definition definition) { return mapper.writeValueAsString(definition); }

    /** Validates a definition; checkTargets also requires code groups, ref targets and rule targets to exist. */
    public Definition parse(String key, JsonNode node, boolean checkTargets) {
        if (!key.matches(KEY)) throw bad("key 는 영문 소문자로 시작하는 2~40자(소문자·숫자·_)여야 합니다.");
        if (node == null || !node.isObject()) throw bad("정의는 JSON 객체여야 합니다.");
        // the groups this definition declares, for its own fields only: reading another definition on the way (a ref's target) keeps its own
        // and gives these back afterwards
        Map<String, List<String>> outer = new LinkedHashMap<>(declared.get());
        declared.get().clear();
        for (CodeGroup group : codeGroups(node.get("codeGroups"))) declared.get().put(group.code(), group.values().stream().map(CodeValue::code).toList());
        if (node.hasNonNull("from")) node = withFrom(key, node.deepCopy(), checkTargets);
        // what the screen is to the work - master data or work - as the model judged it: kept as said, never guessed here
        String kind = null;
        if (node.hasNonNull("kind")) {
            String said = node.get("kind").asString().trim();
            kind = switch (said) { case "master", "기준 정보", "기준정보" -> "master"; case "work", "업무" -> "work";
                default -> throw bad("kind 는 master(기준 정보: 업무가 골라 쓰는 바탕 자료) 또는 work(업무: 날마다 쌓이는 기록) 입니다 (받은 값: " + said + ")."); };
            tools.jackson.databind.node.ObjectNode rest = (tools.jackson.databind.node.ObjectNode) node.deepCopy();
            rest.remove("kind");
            node = rest;
        }
        try {
            Definition d = parsed(key, node, checkTargets);
            // a screen that keeps records is master data or work - said by whoever writes it (a view of other records is neither)
            if (kind == null && checkTargets && RecordStore.keeps(d))
                throw bad("kind 를 적는다: \"master\"(기준 정보: 업무가 골라 쓰는 바탕 자료) 또는 \"work\"(업무: 날마다 쌓이는 기록) - 이 화면 \"" + d.title() + "\" 은 어느 쪽인가.");
            return kind == null ? d : d.withKind(kind);
        } finally { declared.get().clear(); declared.get().putAll(outer); }
    }
    private Definition parsed(String key, JsonNode node, boolean checkTargets) {
        if (checkTargets) {
            known(node, "정의", Set.of("key", "type", "title", "keywords", "fields", "lines", "moreLines", "status", "rules", "summary", "print", "dashboard", "checks", "limits", "effects", "over", "period", "closing", "follows", "screen", "dataOnly", "lookups", "lock", "codeGroups", "calendar", "tree", "take", "ledger", "stock", "uniqueBy", "noCycle", "ledgerView", "stockView", "effective", "noOverlap", "from"));
            for (JsonNode item : node.path("checks")) known(item, "checks", Set.of("left", "op", "right", "lines", "message"));
            for (JsonNode item : node.path("limits")) known(item, "limits", Set.of("field", "lines", "by", "entity", "entityField", "entityLines", "entityBy", "ignore", "entityIgnore", "message"));
            for (JsonNode item : node.path("effects")) { known(item, "effects", Set.of("on", "create", "act", "fill", "expand", "cascade")); known(item.get("create"), "effects.create", Set.of("entity", "set", "lines")); known(item.path("create").get("lines"), "effects.create.lines", Set.of("set")); known(item.get("act"), "effects.act", Set.of("via", "action")); }
            known(node.get("lines"), "lines", Set.of("label", "fields", "min", "max"));
            for (JsonNode set : node.path("moreLines")) known(set, "moreLines", Set.of("name", "label", "fields", "min", "max"));
            known(node.get("status"), "status", Set.of("initial", "values", "actions", "locked", "closed"));
            List<JsonNode> groups = new ArrayList<>(List.of(node.path("fields"), node.path("lines").path("fields")));
            for (JsonNode set : node.path("moreLines")) groups.add(set.path("fields"));
            for (JsonNode group : groups)
                for (JsonNode item : group) {
                    known(item, "항목 " + text(item, "name"), Set.of("name", "label", "type", "required", "search", "codeGroup", "ref", "prefix", "formula", "sum", "fill", "min", "max", "unique", "pick", "decimals", "showWhen", "requiredWhen", "lockWhen"));
                    known(item.get("ref"), "항목 " + text(item, "name") + " 의 ref", Set.of("entity", "label", "columns", "code", "line", "within", "withinTarget"));
                    if (item.path("ref").path("within").isObject()) known(item.path("ref").get("within"), "항목 " + text(item, "name") + " 의 ref.within", Set.of("field", "target"));
                    for (String when : List.of("showWhen", "requiredWhen", "lockWhen")) known(item.get(when), "항목 " + text(item, "name") + " 의 " + when, Set.of("field", "is", "isNot", "not"));
                }
            for (JsonNode value : node.path("status").path("values")) known(value, "status.values", Set.of("code", "label"));
            for (JsonNode action : node.path("status").path("actions")) known(action, "status.actions", Set.of("name", "label", "from", "to", "separate"));
            known(node.get("over"), "over", Set.of("entity", "statuses", "actions", "edit", "create", "mine", "ask"));
            for (JsonNode rule : node.path("rules")) known(rule, "rules", Set.of("type", "action", "entity", "field", "message"));
        }
        if (node.hasNonNull("over")) return over(key, node, checkTargets);
        if (node.hasNonNull("take")) return take(key, node, checkTargets);
        if (node.hasNonNull("ledgerView") || node.hasNonNull("stockView")) {          // (stockView: the name an older version wrote)
            String viewKey = node.hasNonNull("ledgerView") ? "ledgerView" : "stockView";
            List<String> words = titled(key, node, viewKey, List.of("fields", "lines", "moreLines", "status", "rules", "summary", "dashboard", "checks", "limits", "effects", "over", "calendar", "tree", "take", "stock"));
            JsonNode block = node.get(viewKey);
            String show = block.isString() ? block.asString() : text(block, "show");
            if (show.isEmpty()) show = "all";
            if (!LEDGER_VIEWS.contains(show)) throw bad("ledgerView.show 는 " + LEDGER_VIEWS + " 중 하나입니다 (all = 현재 수량·묶음·들고 난 내역을 탭으로).");
            if (checkTargets) known(block.isObject() ? block : null, "ledgerView", Set.of("show", "thing"));
            String thing = block.isObject() && block.hasNonNull("thing") ? text(block, "thing") : null;
            if (thing != null && checkTargets && all().stream().noneMatch(stored -> stored.definition().ledger() != null && thing.equals(stored.definition().ledger().thingEntity())))
                throw bad("ledgerView.thing 은 수량 원장 화면의 대상 자료 key 입니다 (" + thing + "). 있는 대상: "
                        + all().stream().filter(stored -> stored.definition().ledger() != null).map(stored -> stored.definition().ledger().thingEntity()).distinct().toList());
            return new Definition(key, "ledgerView", words.get(0), words.subList(1, words.size()), List.of(), null, null, List.of(), null, null, null, List.of(), List.of(), List.of(), null,
                    null, null, null, List.of(), null, null, List.of(), null, new LedgerView(show, thing), null, null, false, List.of(), null, List.of(), List.of(), null);
        }
        if (node.hasNonNull("calendar")) return calendar(key, node, checkTargets);
        if (node.hasNonNull("tree")) return tree(key, node, checkTargets);
        if (node.hasNonNull("dashboard")) return dashboard(key, node, checkTargets);
        if (node.hasNonNull("summary")) return summary(key, node, checkTargets);
        // "type" is no longer a choice: a screen is its parts. It is still written out (derived) for readers that ask.
        String type = node.hasNonNull("lines") ? "document" : "master";
        String title = text(node, "title");
        if (title.isEmpty() || title.length() > 60) throw bad("title(화면 이름)을 1~60자로 적어야 합니다.");
        List<String> keywords = new ArrayList<>();
        if (node.has("keywords") && node.get("keywords").isArray())
            for (JsonNode word : node.get("keywords")) if (word.isString() && !word.asString().isBlank()) keywords.add(word.asString().trim());
        List<Field> fields = withKeySearch(fields(key, node.get("fields"), "fields", true, checkTargets, null), node);
        Lines lines = null;
        List<LineSet> moreLines = new ArrayList<>();
        if (node.hasNonNull("lines")) {
            JsonNode block = node.get("lines");
            if (!block.isObject()) throw bad("lines 는 {label, fields, min, max} 모양이어야 합니다.");
            String label = text(block, "label");
            int min = block.hasNonNull("min") ? block.get("min").asInt(-1) : 1;
            Integer max = block.hasNonNull("max") ? Integer.valueOf(block.get("max").asInt(-1)) : null;
            if (min < 0 || min > 500 || (max != null && (max < 1 || max > 500 || max < min))) throw bad("lines 의 min 은 0 이상, max 는 1 이상이고 min 보다 작을 수 없습니다.");
            lines = new Lines(label.isEmpty() ? "명세" : label, fields(key, block.get("fields"), "lines.fields", false, checkTargets, fields), min, max);
            if (node.hasNonNull("moreLines") && !node.get("moreLines").isEmpty()) {
                if (!node.get("moreLines").isArray() || node.get("moreLines").size() > 5) throw bad("moreLines 는 줄 표를 5개까지 적은 목록입니다: [{name, label, fields, min, max}]");
                for (JsonNode more : node.get("moreLines")) {
                    String name = text(more, "name"), moreLabel = text(more, "label");
                    if (!name.matches(NAME) || RESERVED.contains(name)) throw bad("moreLines 의 name '" + name + "' 은(는) 영문 camelCase 여야 합니다 (예: materials, steps).");
                    if (fields.stream().anyMatch(field -> field.name().equals(name)) || moreLines.stream().anyMatch(set -> set.name().equals(name))) throw bad("moreLines 의 name " + name + " 이(가) 다른 항목이나 줄 표의 이름과 겹칩니다.");
                    if (moreLabel.isEmpty() || moreLabel.length() > 30) throw bad("moreLines " + name + " 에 label(줄 표 이름)이 필요합니다.");
                    int moreMin = more.hasNonNull("min") ? more.get("min").asInt(-1) : 0;
                    Integer moreMax = more.hasNonNull("max") ? Integer.valueOf(more.get("max").asInt(-1)) : null;
                    if (moreMin < 0 || moreMin > 500 || (moreMax != null && (moreMax < 1 || moreMax > 500 || moreMax < moreMin))) throw bad("moreLines " + name + " 의 min 은 0 이상, max 는 1 이상이고 min 보다 작을 수 없습니다.");
                    moreLines.add(new LineSet(name, moreLabel, fields(key, more.get("fields"), "moreLines." + name + ".fields", false, checkTargets, fields), moreMin, moreMax));
                }
            }
            for (Field field : fields)
                if (field.sum() != null && sumTarget(lines, moreLines, field.sum()) == null)
                    throw bad("항목 " + field.name() + " 의 sum 은 줄 표의 숫자 항목이어야 합니다 (" + field.sum() + "). 첫 줄 표는 \"<항목 name>\", 다른 줄 표는 \"<줄 표 name>.<항목 name>\" 으로 적습니다.");
        } else if (fields.stream().anyMatch(field -> field.sum() != null)) throw bad("sum 은 줄 표(lines)가 있을 때만 씁니다.");
        else if (node.hasNonNull("moreLines") && !node.get("moreLines").isEmpty()) throw bad("moreLines 는 lines(첫 줄 표)가 있을 때 더 붙이는 줄 표입니다. 줄 표가 하나면 lines 만 적습니다.");
        if (fields.stream().noneMatch(field -> field.required() || field.type().equals("serial") || field.type().equals("user")))
            throw bad("적어도 하나의 항목은 required: true 이거나 serial 이어야 합니다.");
        Status status = status(node.get("status"));
        List<Rule> rules = rules(key, node.get("rules"), status, checkTargets);
        Print print = null;
        if (node.hasNonNull("print")) {
            JsonNode block = node.get("print");
            if (!block.isObject()) throw bad("print 는 {title, signers, note} 모양이어야 합니다.");
            if (checkTargets) known(block, "print", Set.of("title", "signers", "note", "logo", "company", "receiver", "fields", "columns", "vat"));
            List<String> signers = new ArrayList<>();
            for (JsonNode signer : block.path("signers")) if (!signer.asString().isBlank()) signers.add(signer.asString().trim());
            if (signers.size() > 6) throw bad("print.signers(결재란)는 6칸까지입니다.");
            String heading = text(block, "title"), note = text(block, "note");
            if (heading.length() > 40 || note.length() > 300) throw bad("print.title 은 40자, print.note 는 300자까지입니다.");
            String receiver = block.hasNonNull("receiver") ? named(fields, text(block, "receiver"), "print.receiver") : null;
            if (receiver != null && fields.stream().noneMatch(field -> field.name().equals(receiver) && field.ref() != null))
                throw bad("print.receiver 는 받는 쪽(거래처 등)을 고르는 ref 항목의 name 입니다. 있는 ref 항목: " + fields.stream().filter(field -> field.ref() != null).map(field -> field.name() + "=" + field.label()).toList());
            List<String> shown = new ArrayList<>(), columns = new ArrayList<>();
            for (JsonNode item : block.path("fields")) shown.add(named(fields, item.asString(), "print.fields"));
            for (JsonNode item : block.path("columns")) {
                if (lines == null) throw bad("print.columns 는 줄 표가 있는 화면에만 씁니다.");
                columns.add(named(lines.fields(), item.asString(), "print.columns"));
            }
            Double vat = block.hasNonNull("vat") && block.get("vat").isNumber() ? Double.valueOf(block.get("vat").asDouble()) : null;
            if (block.hasNonNull("vat") && (vat == null || vat < 0 || vat > 100)) throw bad("print.vat 는 부가세율(%)입니다. 예: 10");
            if (vat != null && fields.stream().noneMatch(field -> field.sum() != null)) throw bad("print.vat 는 줄 합계(sum) 항목이 있는 화면에만 씁니다 (공급가액을 알아야 부가세를 냅니다).");
            print = new Print(heading.isEmpty() ? null : heading, signers, note.isEmpty() ? null : note, block.path("logo").asBoolean(false), block.path("company").asBoolean(false), receiver, shown, columns, vat);
        }
        String period = node.hasNonNull("period") ? text(node, "period") : null;
        if (period != null && !PERIODS.contains(period)) throw bad("period(목록을 처음 열 때의 기간)는 " + PERIODS + " 중 하나입니다.");
        if (period != null && fields.stream().noneMatch(field -> field.type().equals("date"))) throw bad("period 는 날짜 항목이 있는 화면에만 씁니다.");
        // (a screen no longer says how a month's closing goes: closing is the period locks' (see PeriodLocks))
        if (node.hasNonNull("closing") && !text(node, "closing").equals("none"))
            throw bad("closing 은 없습니다: 기간 마감은 \"lock\": {\"group\": \"<마감 묶음>\", \"date\": \"<날짜 항목>\"} 로 적는다.");
        List<Limit> limits = withoutStockCap(limits(key, node.get("limits"), fields, lines, checkTargets), ledgerBlock(node));
        List<Effect> effects = effects(key, node.get("effects"), fields, lines, status, checkTargets);
        for (Effect effect : effects)
            if (effect.fill() != null && limits.stream().noneMatch(limit -> limit.entity().equals(effect.fill().entity()) && limit.entityBy().contains("id")))
                throw bad("effects.fill: 이 자료에 " + effect.fill().entity() + " 을(를) 한도로 하는 limits (entityBy 에 id 포함)가 있어야, 그 자료가 다 찼는지 알 수 있습니다.");
        return new Definition(key, type, title, keywords, fields, lines, status, rules, null, print, null,
                checks(node.get("checks"), fields, lines), limits, effects, null, period, null, null, moreLines, null, ledger(ledgerBlock(node), fields, lines, checkTargets),
                uniqueBy(node.get("uniqueBy"), fields), noCycle(node.get("noCycle"), fields, lines), null, effective(node.get("effective"), fields), follows(node, fields), (node.has("screen") && !node.get("screen").asBoolean(true)) || node.path("dataOnly").asBoolean(false),     // as written / as stored
                lookups(key, node.get("lookups"), fields, checkTargets), lock(node.get("lock"), fields), codeGroups(node.get("codeGroups")), noOverlap(node.get("noOverlap"), fields, status), from(key, node, fields, checkTargets));
    }

    /** One of these fields, named by its name or by the label people see; stored by name. */
    private static String named(List<Field> fields, String given, String where) {
        for (Field field : fields) if (field.name().equals(given)) return field.name();
        for (Field field : fields) if (field.label().equals(given)) return field.name();
        throw bad(where + ": '" + given + "' 은(는) 없는 항목입니다. 있는 항목: " + fields.stream().map(field -> field.name() + "=" + field.label()).toList());
    }

    private List<String> titled(String key, JsonNode node, String part, List<String> never) {
        String title = text(node, "title");
        if (title.isEmpty() || title.length() > 60) throw bad("title(화면 이름)을 1~60자로 적어야 합니다.");
        List<String> keywords = new ArrayList<>(List.of(title));
        if (node.has("keywords") && node.get("keywords").isArray())
            for (JsonNode word : node.get("keywords")) if (word.isString() && !word.asString().isBlank()) keywords.add(word.asString().trim());
        for (String other : never)
            if (node.hasNonNull(other) && !(node.get(other).isArray() && node.get(other).isEmpty())) throw bad(part + " 화면에는 " + other + " 를 적지 않습니다 (자료의 항목과 규칙은 그 자료의 등록 화면에 있습니다).");
        return keywords;
    }

    private Stored source(String entity, String key, String where) {
        Stored stored = entity.matches(KEY) && !entity.equals(key) ? find(entity) : null;
        if (stored == null || stored.definition().summary() != null || stored.definition().dashboard() != null || stored.definition().over() != null
                || stored.definition().calendar() != null || stored.definition().tree() != null || stored.definition().take() != null || stored.definition().ledgerView() != null)
            throw bad(where + ": 자료 " + entity + " 의 등록 화면 정의가 없습니다. 그 화면을 먼저 만들어야 합니다.");
        return stored;
    }

    /** A calendar screen: another entity's records on a month calendar. */
    private List<List<String>> uniqueBy(JsonNode list, List<Field> fields) {
        List<List<String>> out = new ArrayList<>();
        if (list == null || list.isNull() || (list.isArray() && list.isEmpty())) return out;
        if (!list.isArray()) throw bad("uniqueBy 는 겹치면 안 되는 항목 조합의 목록입니다: [[\"itemId\", \"version\"]]");
        for (JsonNode group : list) {
            List<String> names = new ArrayList<>();
            for (JsonNode item : group.isArray() ? group : mapper.createArrayNode().add(group)) {
                String name = named(fields, item.asString(), "uniqueBy");
                Field field = fields.stream().filter(candidate -> candidate.name().equals(name)).findFirst().orElseThrow();
                if (field.computed() || field.type().equals("memo") || field.type().equals("yesno")) throw bad("uniqueBy: " + name + " 은(는) 조합의 열쇠가 될 수 없는 항목입니다 (계산·긴 글·예/아니오).");
                names.add(name);
            }
            if (names.isEmpty() || names.size() > 5) throw bad("uniqueBy 의 조합 하나에는 항목을 1~5개 적습니다.");
            out.add(names);
        }
        return out;
    }

    private Effective effective(JsonNode block, List<Field> fields) {
        if (block == null || block.isNull()) return null;
        String from = text(block, "from"), to = block.hasNonNull("to") ? text(block, "to") : null;
        java.util.function.Function<String, Field> date = name -> fields.stream().filter(field -> (field.name().equals(name) || field.label().equals(name)) && field.type().equals("date")).findFirst().orElse(null);
        Field start = date.apply(from), end = to == null ? null : date.apply(to);
        if (start == null || (to != null && end == null)) throw bad("effective 는 {\"from\": \"<적용 시작일 date 항목>\", \"to\": \"<적용 종료일 date 항목 (선택)>\", \"by\": [\"<기간이 겹치면 안 되는 기준 항목>\"]} 입니다. 있는 날짜 항목: " + fields.stream().filter(field -> field.type().equals("date")).map(Field::name).toList());
        if (!start.required()) throw bad("effective.from 항목 " + start.name() + " 은(는) 필수(required)여야 합니다: 적용 시작일 없이 기간을 따질 수 없습니다.");
        List<String> by = new ArrayList<>();
        for (JsonNode item : block.path("by")) by.add(named(fields, item.asString(), "effective.by"));
        return new Effective(start.name(), end == null ? null : end.name(), by);
    }

    private NoCycle noCycle(JsonNode block, List<Field> fields, Lines lines) {
        if (block == null || block.isNull()) return null;
        String parent = text(block, "parent"), child = text(block, "child");
        Field up = fields.stream().filter(field -> field.name().equals(parent) || field.label().equals(parent)).findFirst().orElse(null);
        // the child is a line field (a BOM with its parts as lines) or a field of the record itself (a BOM kept as one pair per record)
        Field down = lines == null ? null : lines.fields().stream().filter(field -> field.name().equals(child) || field.label().equals(child)).findFirst().orElse(null);
        if (down == null) down = fields.stream().filter(field -> (field.name().equals(child) || field.label().equals(child)) && !field.name().equals(up == null ? "" : up.name())).findFirst().orElse(null);
        if (up == null || up.ref() == null || down == null || down.ref() == null || !up.ref().entity().equals(down.ref().entity()))
            throw bad("noCycle 은 {\"parent\": \"<상위를 가리키는 ref 항목>\", \"child\": \"<하위를 가리키는 ref 항목 (같은 자료를 가리킴)>\"} 입니다. 예: BOM 의 상위 품목과 하위 자재.");
        return new NoCycle(up.name(), down.name());
    }

    /** The ledger part as written ("ledger"), or as an older version wrote it ("stock" with item / warehouse / toWarehouse): the same thing. */
    private static JsonNode ledgerBlock(JsonNode node) {
        if (node.hasNonNull("ledger")) return node.get("ledger");
        JsonNode old = node.get("stock");
        if (old == null || !old.isObject()) return old;
        tools.jackson.databind.node.ObjectNode out = tools.jackson.databind.json.JsonMapper.builder().build().createObjectNode();
        Map<String, String> renamed = Map.of("item", "thing", "warehouse", "place", "toWarehouse", "toPlace", "itemEntity", "thingEntity", "warehouseEntity", "placeEntity");
        for (Map.Entry<String, JsonNode> entry : old.properties()) out.set(renamed.getOrDefault(entry.getKey(), entry.getKey()), entry.getValue());
        return out;
    }
    private Ledger ledger(JsonNode block, List<Field> fields, Lines lines, boolean checkTargets) {
        if (block == null || block.isNull()) return null;
        if (!block.isObject()) throw bad("ledger 는 {direction, thing, quantity, place, unitCost, date} 모양이어야 합니다.");
        if (checkTargets) known(block, "ledger", Set.of("direction", "thing", "quantity", "place", "unitCost", "date", "thingEntity", "placeEntity", "lot", "toPlace", "lotWhen"));
        String direction = text(block, "direction");
        if (!direction.equals("in") && !direction.equals("out") && !direction.equals("move") && !direction.equals("count")) throw bad("ledger.direction 은 \"in\"(들어옴), \"out\"(나감), \"move\"(위치에서 위치로 옮김), \"count\"(센 수량으로 장부를 맞춤) 중 하나입니다.");
        List<Field> all = new ArrayList<>(fields);
        if (lines != null) all.addAll(lines.fields());
        java.util.function.BiFunction<String, String, Field> find = (part, kind) -> {
            String name = block.hasNonNull(part) ? text(block, part) : "";
            Field found = lines == null ? null : lines.fields().stream().filter(field -> field.name().equals(name) || field.label().equals(name)).findFirst().orElse(null);
            if (found == null) found = fields.stream().filter(field -> field.name().equals(name) || field.label().equals(name)).findFirst().orElse(null);
            if (found == null || !found.type().equals(kind)) throw bad("ledger." + part + " 는 이 화면의 " + kind + " 항목 name 입니다 (받은 값: " + name + "). 있는 " + kind + " 항목: " + all.stream().filter(field -> field.type().equals(kind)).map(Field::name).toList());
            return found;
        };
        Field thing = find.apply("thing", "ref"), quantity = find.apply("quantity", "number"), place = find.apply("place", "ref");
        if (!place.required()) throw bad("ledger.place 항목 " + place.name() + " 은(는) 필수(required)여야 합니다: 수량은 위치 없이 움직이지 않습니다.");
        if (quantity.formula() != null || quantity.sum() != null) throw bad("ledger.quantity 는 직접 입력하는 수량 항목입니다.");
        Field cost = block.hasNonNull("unitCost") ? find.apply("unitCost", "number") : null, date = block.hasNonNull("date") ? find.apply("date", "date") : null;
        if ((direction.equals("out") || direction.equals("move")) && cost != null) throw bad("ledger.unitCost 는 in·count 일 때만 적습니다. out 과 move 의 원가는 꺼내 쓴 묶음의 단가로 정해집니다.");
        Field to = null;
        if (direction.equals("move")) {
            if (!block.hasNonNull("toPlace")) throw bad("ledger.direction 이 move 이면 ledger.toPlace (받는 위치 ref 항목 name) 가 필요합니다. place 는 보내는 위치입니다.");
            to = find.apply("toPlace", "ref");
            if (!to.required() || !to.ref().entity().equals(place.ref().entity()) || to.name().equals(place.name()))
                throw bad("ledger.toPlace 항목 " + to.name() + " 은(는) 보내는 위치와 다른 항목이고, 같은 위치 자료를 가리키는 필수 ref 여야 합니다.");
        } else if (block.hasNonNull("toPlace")) throw bad("ledger.toPlace 는 direction 이 move 일 때만 적습니다.");
        if (date == null) date = fields.stream().filter(field -> field.type().equals("date") && field.required()).findFirst().orElse(null);
        Field lot = block.hasNonNull("lot") ? find.apply("lot", "text") : null;
        if (lot != null && lot.required()) throw bad("ledger.lot 항목 " + lot.name() + " 은(는) 필수로 두지 않습니다: LOT 관리 품목에만 쓰는 값입니다.");
        LotWhen lotWhen = null;
        if (block.hasNonNull("lotWhen")) {
            JsonNode rule = block.get("lotWhen");
            if (checkTargets) known(rule, "ledger.lotWhen", Set.of("field", "is"));
            String by = text(rule, "field");
            List<String> values = new ArrayList<>();
            for (JsonNode value : rule.path("is")) values.add(value.asString());
            if (by.isEmpty() || values.isEmpty()) throw bad("ledger.lotWhen 은 {field: <" + thing.ref().entity() + " 의 항목>, is: [<묶음 번호로 관리한다는 값>]} 입니다.");
            if (checkTargets) {
                Stored target = find(thing.ref().entity());
                if (target == null || target.definition().field(by) == null) throw bad("ledger.lotWhen.field: " + thing.ref().entity() + " 에 " + by + " 항목이 없습니다.");
            }
            lotWhen = new LotWhen(by, values);
        }
        return new Ledger(direction, thing.name(), quantity.name(), place.name(), cost == null ? null : cost.name(), date == null ? null : date.name(), thing.ref().entity(), place.ref().entity(), lot == null ? null : lot.name(), to == null ? null : to.name(), lotWhen);
    }

    /** The limit of `target` that is measured against `from`: what tells how much of an earlier record is still open. */
    public static Limit takeLimit(Definition target, String from) {
        return target.limits() == null ? null : target.limits().stream().filter(limit -> limit.entity().equals(from)).findFirst().orElse(null);
    }

    private Definition take(String key, JsonNode node, boolean checkTargets) {
        List<String> words = titled(key, node, "take", List.of("fields", "lines", "moreLines", "status", "rules", "summary", "dashboard", "checks", "limits", "effects", "over", "calendar", "tree"));
        JsonNode block = node.get("take");
        if (!block.isObject()) throw bad("take 는 {entity, from, statuses, set, lines, columns} 모양이어야 합니다.");
        String entity = text(block, "entity"), from = text(block, "from");
        List<String> statuses = new ArrayList<>(), columns = new ArrayList<>();
        for (JsonNode item : block.path("statuses")) statuses.add(item.asString());
        Map<String, String> set = new LinkedHashMap<>(), lineSet = new LinkedHashMap<>();
        for (Map.Entry<String, JsonNode> entry : block.path("set").properties()) set.put(entry.getKey(), entry.getValue().asString());
        for (Map.Entry<String, JsonNode> entry : block.path("lines").path("set").properties()) lineSet.put(entry.getKey(), entry.getValue().asString());
        for (Map.Entry<String, JsonNode> entry : block.path("lineSet").properties()) lineSet.put(entry.getKey(), entry.getValue().asString());      // as a stored definition is written out
        for (JsonNode item : block.path("columns")) columns.add(item.asString());
        List<String> ask = new ArrayList<>();
        for (JsonNode item : block.path("lines").path("ask")) ask.add(item.asString());
        for (JsonNode item : block.path("ask")) ask.add(item.asString());          // as a stored definition is written out
        String group = block.hasNonNull("group") ? text(block, "group") : "source";
        if (!group.equals("source") && !group.equals("same")) throw bad("take.group 은 \"source\"(앞 단계 한 건마다 한 건) 또는 \"same\"(위쪽 값이 같은 줄끼리 한 건) 입니다.");
        if (checkTargets) {
            known(block, "take", Set.of("entity", "from", "statuses", "set", "lines", "lineSet", "columns", "group", "ask"));
            known(block.get("lines"), "take.lines", Set.of("set", "ask"));
            Definition target = source(entity, key, "take.entity").definition(), earlier = source(from, key, "take.from").definition();
            Limit limit = takeLimit(target, from);
            if (limit == null)
                throw bad("take: " + entity + " 에 " + from + " 을(를) 한도로 하는 limits 가 없어, 앞 단계에 얼마가 남았는지 알 수 없습니다. 먼저 " + entity + " 등록 화면에 한도를 넣어야 합니다 "
                        + "(예: {\"field\": \"quantity\", \"lines\": true, \"by\": [\"<" + from + " 을(를) 가리키는 ref 항목>\", \"itemId\"], \"entity\": \"" + from + "\", \"entityField\": \"quantity\", \"entityLines\": true, \"entityBy\": [\"id\", \"itemId\"], \"message\": \"...\"}).");
            if (group.equals("same") && !combinable(target, limit))
                throw bad("take.group same: " + entity + " 은(는) " + from + " 을(를) 가리키는 항목이 위쪽에 있어 한 건이 앞 단계 한 건에만 속합니다. 여러 건을 한 건으로 묶으려면 " + entity + " 등록 화면에서 그 항목을 줄 표로 옮겨야 합니다 (한도의 by 는 그대로).");
            if (limit.lines() && !limit.entityLines()) throw bad("take: " + entity + " 의 한도가 줄 수량을 " + from + " 의 위쪽 수량에 견줍니다. 이 모양은 이어받기 화면으로 만들 수 없습니다.");
            if (!statuses.isEmpty() && earlier.status() == null) throw bad("take.statuses 는 상태가 있는 자료에만 씁니다 (" + from + " 에는 상태가 없습니다).");
            for (String code : statuses) if (earlier.status().values().stream().noneMatch(value -> value.code().equals(code)))
                throw bad("take.statuses: " + from + " 에 " + code + " 상태가 없습니다. 있는 상태: " + earlier.status().values().stream().map(value -> value.code() + "=" + value.label()).toList());
            List<Field> targetLines = target.lines() == null ? List.of() : target.lines().fields(), earlierLines = earlier.lines() == null ? List.of() : earlier.lines().fields();
            Map<String, String> headSet = new LinkedHashMap<>(), rowSet = new LinkedHashMap<>();
            for (Map.Entry<String, String> entry : set.entrySet()) {
                String into = named(target.fields(), entry.getKey(), "take.set (" + entity + " 의 위쪽 항목)");
                // (when the earlier record is taken line by line, a value may come from the line: its price into a record that holds one item)
                String come = entry.getValue().equals("id") || entry.getValue().equals("today") ? entry.getValue()
                        : limit.entityLines() && earlierLines.stream().anyMatch(field -> field.name().equals(entry.getValue()) || field.label().equals(entry.getValue())) ? named(earlierLines, entry.getValue(), "take.set")
                        : named(earlier.fields(), entry.getValue(), "take.set (" + from + " 의 항목, 또는 id, today)");
                if (target.field(into).computed()) throw bad("take.set: " + into + " 은(는) 서버가 계산하는 항목입니다.");
                headSet.put(into, come);
            }
            for (Map.Entry<String, String> entry : lineSet.entrySet()) {
                if (!limit.lines()) throw bad("take.lines 는 " + entity + " 의 한도가 줄 수량일 때만 씁니다.");
                String into = named(targetLines, entry.getKey(), "take.lines.set (" + entity + " 의 줄 항목)");
                String come = earlierLines.stream().anyMatch(field -> field.name().equals(entry.getValue()) || field.label().equals(entry.getValue())) ? named(earlierLines, entry.getValue(), "take.lines.set") : named(earlier.fields(), entry.getValue(), "take.lines.set (" + from + " 의 줄 항목 또는 위쪽 항목)");
                rowSet.put(into, come);
            }
            set = headSet; lineSet = rowSet;
            List<String> typed = new ArrayList<>();
            List<Field> rowFields = limit.lines() ? targetLines : target.fields();       // a record that holds one item is itself the row
            for (String name : ask) {
                String into = named(rowFields, name, "take.ask (" + entity + " 의 항목)");
                Field field = rowFields.stream().filter(candidate -> candidate.name().equals(into)).findFirst().orElseThrow();
                // the quantity and what is handed over are in the row already: naming them again asks for nothing more
                if (into.equals(limit.field()) || limit.by().contains(into) || lineSet.containsKey(into) || (!limit.lines() && set.containsKey(into))) continue;
                if (field.computed() || !List.of("text", "number", "date", "time", "yesno", "ref").contains(field.type()))
                    throw bad("take.lines.ask: " + into + " 은(는) 줄에서 직접 적거나 고를 수 있는 글자·숫자·날짜·시각·예/아니오·고르는 항목이어야 합니다 (계산 항목은 안 됩니다).");
                typed.add(into);
            }
            ask = typed;
            // Every line of the new record must be complete from the earlier one alone: nothing is typed in a row but the quantity.
            if (limit.lines())
                for (Field field : targetLines)
                    if (field.required() && !field.computed() && !field.name().equals(limit.field()) && !limit.by().contains(field.name()) && !lineSet.containsKey(field.name()) && !ask.contains(field.name()))
                        throw bad("take: " + entity + " 의 줄 필수 항목 " + field.name() + "(" + field.label() + ") 을(를) 어디서 가져올지 없습니다. take.lines.set 에 {\"" + field.name() + "\": \"<" + from + " 의 줄 항목>\"} 을 적습니다. " + from + " 의 줄 항목: " + names(earlierLines));
            List<Field> shown = new ArrayList<>(earlier.fields());
            shown.addAll(earlierLines);
            List<String> kept = new ArrayList<>();
            for (String column : columns) kept.add(named(shown, column, "take.columns (" + from + " 의 항목)"));
            columns = kept;
        }
        return new Definition(key, "take", words.get(0), words.subList(1, words.size()), List.of(), null, null, List.of(), null, null, null, List.of(), List.of(), List.of(), null,
                null, null, null, List.of(), new Take(entity, from, statuses, set, lineSet, columns, group, ask), null, List.of(), null, null, null, null, false, List.of(), null, List.of(), List.of(), null);
    }

    private Definition calendar(String key, JsonNode node, boolean checkTargets) {
        List<String> words = titled(key, node, "calendar", List.of("fields", "lines", "moreLines", "status", "rules", "summary", "dashboard", "checks", "limits", "effects", "over", "tree", "take"));
        JsonNode block = node.get("calendar");
        if (!block.isObject()) throw bad("calendar 는 {entity, date, end, label} 모양이어야 합니다.");
        String entity = text(block, "entity"), date = text(block, "date"), end = block.hasNonNull("end") ? text(block, "end") : null, label = block.hasNonNull("label") ? text(block, "label") : null;
        if (checkTargets) {
            known(block, "calendar", Set.of("entity", "date", "end", "label"));
            Definition source = source(entity, key, "calendar.entity").definition();
            date = named(source.fields(), date, "calendar.date");
            if (end != null) end = named(source.fields(), end, "calendar.end");
            for (String name : end == null ? List.of(date) : List.of(date, end)) {
                String wanted = name;
                if (source.fields().stream().noneMatch(field -> field.name().equals(wanted) && field.type().equals("date")))
                    throw bad("calendar.date, calendar.end 는 " + entity + " 의 날짜 항목입니다. 있는 날짜 항목: " + source.fields().stream().filter(field -> field.type().equals("date")).map(field -> field.name() + "=" + field.label()).toList());
            }
            if (label != null) label = named(source.fields(), label, "calendar.label");
        }
        return new Definition(key, "calendar", words.get(0), words.subList(1, words.size()), List.of(), null, null, List.of(), null, null, null, List.of(), List.of(), List.of(), null,
                null, new Calendar(entity, date, end, label), null);
    }

    /** A tree screen: a hierarchy of records. */
    private Definition tree(String key, JsonNode node, boolean checkTargets) {
        List<String> words = titled(key, node, "tree", List.of("fields", "lines", "moreLines", "status", "rules", "summary", "dashboard", "checks", "limits", "effects", "over", "calendar", "take"));
        JsonNode block = node.get("tree");
        if (!block.isObject()) throw bad("tree 는 {entity, parent, child, label, columns} 모양이어야 합니다.");
        String entity = text(block, "entity"), parent = text(block, "parent"), child = block.hasNonNull("child") ? text(block, "child") : null, label = block.hasNonNull("label") ? text(block, "label") : null;
        List<String> columns = new ArrayList<>();
        for (JsonNode item : block.path("columns")) columns.add(item.asString());
        if (checkTargets) {
            known(block, "tree", Set.of("entity", "parent", "child", "label", "columns"));
            Definition source = source(entity, key, "tree.entity").definition();
            parent = named(source.fields(), parent, "tree.parent");
            Field up = source.field(parent);
            if (up.ref() == null) throw bad("tree.parent 는 상위를 고르는 ref 항목입니다. " + entity + " 의 ref 항목: " + source.fields().stream().filter(field -> field.ref() != null).map(field -> field.name() + "=" + field.label()).toList());
            if (child == null) {
                if (!up.ref().entity().equals(entity)) throw bad("tree.parent 는 같은 자료(" + entity + ")를 가리키는 ref 항목이어야 합니다 (상위 부서, 상위 분류). 다른 자료 두 개를 잇는 구조(BOM)라면 tree.child 도 적습니다.");
                if (label != null) label = named(source.fields(), label, "tree.label");
            } else {
                child = named(source.fields(), child, "tree.child");
                Field down = source.field(child);
                if (down.ref() == null || !down.ref().entity().equals(up.ref().entity())) throw bad("tree.child 는 tree.parent 와 같은 자료를 가리키는 ref 항목이어야 합니다 (상위 품목과 하위 품목).");
            }
            List<String> namedColumns = new ArrayList<>();
            for (String column : columns) namedColumns.add(named(source.fields(), column, "tree.columns"));
            if (namedColumns.size() > 6) throw bad("tree.columns 는 6개까지입니다.");
            columns = namedColumns;
        }
        return new Definition(key, "tree", words.get(0), words.subList(1, words.size()), List.of(), null, null, List.of(), null, null, null, List.of(), List.of(), List.of(), null,
                null, null, new Tree(entity, parent, child, label, columns));
    }

    /** A work screen: another entity's records under a screen of their own (approve, hand over, look up). */
    private Definition over(String key, JsonNode node, boolean checkTargets) {
        String title = text(node, "title");
        if (title.isEmpty() || title.length() > 60) throw bad("title(화면 이름)을 1~60자로 적어야 합니다.");
        List<String> keywords = new ArrayList<>();
        if (node.has("keywords") && node.get("keywords").isArray())
            for (JsonNode word : node.get("keywords")) if (word.isString() && !word.asString().isBlank()) keywords.add(word.asString().trim());
        JsonNode block = node.get("over");
        if (!block.isObject()) throw bad("over 는 {entity, statuses, actions, edit, create} 모양이어야 합니다.");
        if (checkTargets)
            for (String part : List.of("fields", "lines", "status", "rules", "summary", "dashboard", "checks", "limits", "effects"))
                if (node.hasNonNull(part) && !(node.get(part).isArray() && node.get(part).isEmpty())) throw bad("over 화면에는 " + part + " 를 적지 않습니다 (자료의 항목과 규칙은 그 자료의 등록 화면에 있습니다).");
        String entity = text(block, "entity");
        List<String> statuses = new ArrayList<>(), actions = new ArrayList<>();
        for (JsonNode item : block.path("statuses")) statuses.add(item.asString());
        for (JsonNode item : block.path("actions")) actions.add(item.asString());
        if (checkTargets) {
            Stored stored = entity.matches(KEY) && !entity.equals(key) ? find(entity) : null;
            if (stored == null || stored.definition().summary() != null || stored.definition().dashboard() != null || stored.definition().over() != null)
                throw bad("over.entity: 자료 " + entity + " 의 등록 화면 정의가 없습니다. 그 화면을 먼저 만들어야 합니다.");
            Status status = stored.definition().status();
            if ((!statuses.isEmpty() || !actions.isEmpty()) && status == null) throw bad("over.statuses, over.actions 는 상태가 있는 자료에만 씁니다 (" + entity + " 에는 상태가 없습니다).");
            for (String code : statuses) if (status.values().stream().noneMatch(value -> value.code().equals(code)))
                throw bad("over.statuses: " + entity + " 에 " + code + " 상태가 없습니다. 있는 상태: " + status.values().stream().map(value -> value.code() + "=" + value.label()).toList());
            for (String name : actions) if (status.actions().stream().noneMatch(action -> action.name().equals(name)))
                throw bad("over.actions: " + entity + " 에 " + name + " 동작이 없습니다. 있는 동작: " + status.actions().stream().map(action -> action.name() + "=" + action.label()).toList() + ". 없는 동작이면 먼저 그 자료의 등록 화면에 추가해야 합니다.");
        }
        Map<String, List<String>> ask = new LinkedHashMap<>();
        if (block.hasNonNull("ask")) {
            if (!block.get("ask").isObject()) throw bad("over.ask 는 {\"<동작 name>\": [\"<그 동작과 함께 적을 항목 name>\", ...]} 입니다.");
            Stored stored = find(entity);
            for (Map.Entry<String, JsonNode> entry : block.get("ask").properties()) {
                if (!actions.contains(entry.getKey())) throw bad("over.ask: " + entry.getKey() + " 은(는) 이 화면의 동작(over.actions)이 아닙니다: " + actions);
                List<String> fields = new ArrayList<>();
                for (JsonNode name : entry.getValue().isArray() ? entry.getValue() : mapper.createArrayNode().add(entry.getValue())) {
                    Field field = stored == null ? null : stored.definition().field(name.asString());
                    if (stored != null && (field == null || field.computed()))
                        throw bad("over.ask: " + entity + " 에 적을 수 있는 " + name.asString() + " 항목이 없습니다. 없는 항목이면 먼저 그 자료에 추가한다. 있는 항목: " + stored.definition().fields().stream().filter(one -> !one.computed()).map(Field::name).toList());
                    fields.add(name.asString());
                }
                if (!fields.isEmpty()) ask.put(entry.getKey(), fields);
            }
        }
        return new Definition(key, "over", title, keywords, List.of(), null, null, List.of(), null, null, null, List.of(), List.of(), List.of(),
                new Over(entity, statuses, actions, block.path("edit").asBoolean(false), block.path("create").asBoolean(false), mineOf(block, entity), ask), null, null, null);
    }

    /** A dashboard: chart panels only, each one a summary screen's chart. */
    private Definition dashboard(String key, JsonNode node, boolean checkTargets) {
        String title = text(node, "title");
        if (title.isEmpty() || title.length() > 60) throw bad("title(화면 이름)을 1~60자로 적어야 합니다.");
        List<String> keywords = new ArrayList<>();
        if (node.has("keywords") && node.get("keywords").isArray())
            for (JsonNode word : node.get("keywords")) if (word.isString() && !word.asString().isBlank()) keywords.add(word.asString().trim());
        JsonNode block = node.get("dashboard");
        if (!block.isObject()) throw bad("dashboard 는 {panels: [...]} 모양이어야 합니다.");
        if (checkTargets) {
            known(block, "dashboard", Set.of("panels"));
            for (String part : List.of("fields", "lines", "status", "rules", "summary"))
                if (node.hasNonNull(part) && !(node.get(part).isArray() && node.get(part).isEmpty())) throw bad("dashboard 화면에는 " + part + " 를 적지 않습니다 (패널은 이미 있는 집계 화면을 가리킵니다).");
        }
        List<Panel> panels = new ArrayList<>();
        for (JsonNode item : block.path("panels")) {
            if (checkTargets) known(item, "dashboard.panels", Set.of("summary", "chart", "value", "title", "width"));
            String from = text(item, "summary"), chart = text(item, "chart"), value = text(item, "value"), heading = text(item, "title");
            int width = item.hasNonNull("width") ? item.get("width").asInt(0) : 1;
            if (width < 1 || width > 3) throw bad("dashboard.panels 의 width 는 1(3분의 1), 2(3분의 2), 3(전체 너비) 입니다.");
            if (checkTargets) {
                Stored stored = from.matches(KEY) ? find(from) : null;
                if (stored == null || stored.definition().summary() == null) {
                    List<String> known = new ArrayList<>();
                    for (Stored other : all()) if (other.definition().summary() != null) known.add(other.definition().key());
                    throw bad("dashboard.panels 의 summary 는 이미 있는 집계 화면의 key 입니다 (" + from + " 은 없음). 있는 집계 화면: " + known + ". 필요한 집계 화면이 없으면 그것부터 만들어야 합니다.");
                }
                Summary source = stored.definition().summary();
                List<String> labels = source.values().stream().map(Value::label).toList();
                if (chart.isEmpty()) chart = source.chart() != null ? source.chart().type() : "bar";
                if (value.isEmpty()) value = source.chart() != null ? source.chart().value() : labels.get(0);
                if (!labels.contains(value)) throw bad("dashboard.panels 의 value 는 " + from + " 의 values label 중 하나입니다: " + labels);
                if (heading.isEmpty()) heading = stored.definition().title();
            }
            if (!PANEL_KINDS.contains(chart)) throw bad("dashboard.panels 의 chart 는 " + PANEL_KINDS + " 중 하나입니다.");
            panels.add(new Panel(from, chart, value, heading, width));
        }
        if (panels.isEmpty() || panels.size() > 12) throw bad("dashboard.panels 는 1~12개여야 합니다.");
        return new Definition(key, "dashboard", title, keywords, List.of(), null, null, List.of(), null, null, new Dashboard(panels), List.of(), List.of(), List.of(), null, null, null, null);
    }

    /** A summary screen: it has no fields of its own; everything it shows comes from the entity it gathers. */
    private Definition summary(String key, JsonNode node, boolean checkTargets) {
        String title = text(node, "title");
        if (title.isEmpty() || title.length() > 60) throw bad("title(화면 이름)을 1~60자로 적어야 합니다.");
        List<String> keywords = new ArrayList<>();
        if (node.has("keywords") && node.get("keywords").isArray())
            for (JsonNode word : node.get("keywords")) if (word.isString() && !word.asString().isBlank()) keywords.add(word.asString().trim());
        JsonNode block = node.get("summary");
        if (!block.isObject()) throw bad("summary 는 {entity, groupBy, values, ...} 모양이어야 합니다.");
        if (checkTargets) {
            known(block, "summary", Set.of("entity", "lines", "groupBy", "values", "filters", "chart", "compare", "share", "top", "cumulative"));
            known(block.get("compare"), "summary.compare", Set.of("type", "value", "label", "entity", "field", "groupBy", "by", "lines", "balance"));
            for (String part : List.of("fields", "lines", "status", "rules"))
                if (node.hasNonNull(part) && !(node.get(part).isArray() && node.get(part).isEmpty())) throw bad("summary 화면에는 " + part + " 를 적지 않습니다 (보여 줄 것은 summary 안에 적습니다).");
            for (JsonNode group : block.path("groupBy")) known(group, "summary.groupBy", Set.of("field", "by", "label"));
            for (JsonNode value : block.path("values")) known(value, "summary.values", Set.of("label", "op", "field", "between"));
            known(block.get("chart"), "summary.chart", Set.of("type", "value"));
        }
        String entity = text(block, "entity");
        boolean lines = block.path("lines").asBoolean(false);
        Definition source = null;
        if (checkTargets) {
            Stored stored = entity.matches(KEY) && !entity.equals(key) ? find(entity) : null;
            if (stored == null) throw bad("summary.entity: 모을 자료 " + entity + " 의 정의가 없습니다.");
            source = stored.definition();
            if (source.summary() != null) throw bad("summary.entity 는 자료를 저장하는 화면이어야 합니다 (" + entity + " 는 집계 화면입니다).");
            if (lines && source.lines() == null) throw bad("summary.lines: " + entity + " 에는 줄 표가 없습니다.");
        }
        List<Group> groups = new ArrayList<>();
        for (JsonNode item : block.path("groupBy")) {
            String field = text(item, "field"), by = item.hasNonNull("by") ? text(item, "by") : null, label = text(item, "label");
            if (source != null) {
                Field found = sourceField(source, field, lines);
                if (field.equals("id")) {                  // each record on its own line (one order, one request)
                    if (label.isEmpty()) label = source.title().replaceAll("\\s*(등록|관리|입력)$", "");
                    groups.add(new Group("id", null, label));
                    continue;
                }
                if (found == null && !(field.equals("status") && source.status() != null))
                    throw bad("summary.groupBy: " + entity + " 에 " + field + " 항목이 없습니다. 쓸 수 있는 항목: " + sourceNames(source, lines) + " (자료 한 건씩 보려면 id)");
                boolean date = found != null && found.type().equals("date");
                if (date && by == null) by = "month";
                if (by != null && (!date || !DATE_PARTS.contains(by))) throw bad("summary.groupBy 의 by 는 날짜 항목에만 쓰고 " + DATE_PARTS + " 중 하나입니다 (" + field + ").");
                if (label.isEmpty()) label = found == null ? "상태" : date ? (by.equals("month") ? "월" : by.equals("year") ? "연도" : found.label()) : found.label();
            }
            groups.add(new Group(field, by, label));
        }
        if (groups.isEmpty() || groups.size() > 2) throw bad("summary.groupBy 는 1~2개여야 합니다.");
        List<Value> values = new ArrayList<>();
        Set<String> labels = new LinkedHashSet<>();
        for (JsonNode item : block.path("values")) {
            String label = text(item, "label"), op = text(item, "op"), field = item.hasNonNull("field") ? text(item, "field") : null;
            if (!OPS.contains(op)) throw bad("summary.values 의 op 는 " + OPS + " 중 하나입니다.");
            List<String> between = null;
            if (item.hasNonNull("between")) {
                between = new ArrayList<>();
                for (JsonNode name : item.get("between")) between.add(name.asString());
                if (between.size() != 2 || op.equals("count")) throw bad("summary.values 의 between 은 [시작 날짜 항목, 끝 날짜 항목] 두 개이고 op 는 avg|sum|min|max 입니다.");
                if (source != null) for (String name : between) {
                    Field date = source.field(name);
                    if (date == null || !date.type().equals("date")) throw bad("summary.values 의 between 은 " + entity + " 의 날짜 항목이어야 합니다 (" + name + ").");
                }
                field = null;
                if (label.isEmpty()) label = "일수";
            }
            if (op.equals("count") || between != null) field = null;
            else if (source != null) {
                Field found = sourceField(source, field == null ? "" : field, lines);
                if (found == null || !found.type().equals("number")) throw bad("summary.values: " + op + " 은(는) 숫자 항목에 씁니다. " + entity + " 의 숫자 항목: " + sourceNumbers(source, lines));
                if (lines && source.field(field) != null && source.lines().fields().stream().noneMatch(line -> line.name().equals(found.name())))
                    throw bad("summary.lines 가 true 이면 줄 표의 숫자 항목을 계산합니다 (" + field + " 는 위쪽 항목이라 줄마다 거듭 더해집니다). 줄 표의 숫자 항목: " + sourceNumbers(source, true) + ", 또는 lines 를 빼세요.");
                if (label.isEmpty()) label = found.label();
            }
            if (label.isEmpty()) label = op.equals("count") ? "건수" : field;
            if (!labels.add(label)) throw bad("summary.values 의 label 이 겹칩니다 (" + label + ").");
            values.add(new Value(label, op, field, between));
        }
        if (values.isEmpty() || values.size() > 6) throw bad("summary.values 는 1~6개여야 합니다.");
        List<String> filters = new ArrayList<>();
        for (JsonNode item : block.path("filters")) {
            String field = item.asString();
            if (source != null && source.field(field) == null && !(field.equals("status") && source.status() != null))
                throw bad("summary.filters: " + entity + " 에 " + field + " 항목이 없습니다 (줄 표 항목은 조회 조건으로 못 씁니다). 쓸 수 있는 항목: " + sourceNames(source, false));
            filters.add(field);
        }
        // A summary is always asked for a period and for the things it is grouped by: with no filters written, those are the conditions.
        if (filters.isEmpty() && source != null) {
            for (Group group : groups) { Field field = source.field(group.field()); if (field != null && field.type().equals("date")) filters.add(field.name()); }
            if (filters.isEmpty()) for (Field field : source.fields()) if (field.type().equals("date")) { filters.add(field.name()); break; }
            for (Group group : groups) { Field field = source.field(group.field()); if (field != null && (field.type().equals("ref") || field.type().equals("code")) && !filters.contains(field.name())) filters.add(field.name()); }
            for (Field field : source.fields()) if (filters.size() < 3 && field.type().equals("ref") && field.required() && !filters.contains(field.name())) filters.add(field.name());
            if (source.status() != null) filters.add("status");
        }
        Chart chart = null;
        if (block.hasNonNull("chart")) {
            String type = text(block.get("chart"), "type"), value = text(block.get("chart"), "value");
            if (!CHARTS.contains(type)) throw bad("summary.chart.type 은 " + CHARTS + " 중 하나입니다.");
            if (value.isEmpty()) value = values.get(0).label();
            if (!labels.contains(value)) throw bad("summary.chart.value 는 values 의 label 중 하나입니다: " + labels);
            chart = new Chart(type, value);
        }
        Compare compare = null;
        if (block.hasNonNull("compare")) {
            JsonNode with = block.get("compare");
            String type = text(with, "type"), of = text(with, "value"), label = text(with, "label");
            if (of.isEmpty()) of = values.get(0).label();
            if (!labels.contains(of)) throw bad("summary.compare.value 는 values 의 label 중 하나입니다: " + labels);
            if (type.equals("plan") || type.equals("minus")) {
                boolean otherLines = with.path("lines").asBoolean(false);
                String planEntity = text(with, "entity"), planField = text(with, "field");
                List<String> planGroups = new ArrayList<>();
                for (JsonNode item : with.path("groupBy")) planGroups.add(item.asString());
                if (planGroups.size() != groups.size()) throw bad("summary.compare.groupBy 는 계획 자료의 항목을 summary.groupBy 와 같은 순서·같은 개수(" + groups.size() + "개)로 적습니다.");
                if (checkTargets) {
                    Stored plan = planEntity.matches(KEY) ? find(planEntity) : null;
                    if (plan == null || plan.definition().summary() != null || plan.definition().dashboard() != null) throw bad("summary.compare.entity: 견줄 자료 " + planEntity + " 의 정의가 없습니다. 그 자료를 등록하는 화면을 먼저 만들어야 합니다.");
                    if (otherLines && plan.definition().lines() == null) throw bad("summary.compare.lines: " + planEntity + " 에는 줄 표가 없습니다.");
                    Field number = sourceField(plan.definition(), planField, otherLines);
                    if (number == null || !number.type().equals("number")) throw bad("summary.compare.field 는 " + planEntity + " 의 숫자 항목입니다: " + sourceNumbers(plan.definition(), otherLines));
                    for (int index = 0; index < planGroups.size(); index++) {
                        Field mine = sourceField(source, groups.get(index).field(), lines), theirs = sourceField(plan.definition(), planGroups.get(index), otherLines);
                        if (theirs == null) throw bad("summary.compare.groupBy: " + planEntity + " 에 " + planGroups.get(index) + " 항목이 없습니다. 있는 항목: " + sourceNames(plan.definition(), otherLines));
                        boolean same = groups.get(index).field().equals("id") ? theirs.ref() != null && theirs.ref().entity().equals(entity)        // the record itself <-> the field that points at it
                                : mine != null && (mine.type().equals(theirs.type()) && (mine.ref() == null || (theirs.ref() != null && mine.ref().entity().equals(theirs.ref().entity()))));
                        if (!same) throw bad("summary.compare.groupBy: " + planGroups.get(index) + " 은(는) " + groups.get(index).field() + " 와(과) 같은 종류여야 맞춰 볼 수 있습니다 (같은 자료를 고르는 항목끼리, 날짜는 날짜끼리).");
                    }
                }
                String balance = text(with, "balance");
                compare = new Compare(type, of, label.isEmpty() ? (type.equals("plan") ? "계획" : "처리") : label, planEntity, planField, planGroups, null, otherLines,
                        type.equals("minus") ? (balance.isEmpty() ? "잔량" : balance) : null);
            } else if (type.equals("previous")) {
                String by = text(with, "by");
                if (!by.equals("month") && !by.equals("year")) throw bad("summary.compare.by 는 month(전월) 또는 year(전년 같은 때) 입니다.");
                String unit = groups.get(0).by();
                if (checkTargets && (unit == null || unit.equals("day") || (unit.equals("year") && by.equals("month"))))
                    throw bad("전기 대비(compare previous)는 첫 번째 groupBy 가 날짜를 month 또는 year 로 묶은 것이어야 합니다" + (by.equals("month") ? " (전월 대비는 month)." : "."));
                compare = new Compare("previous", of, label.isEmpty() ? (by.equals("month") ? "전월" : "전년") : label, null, null, List.of(), by, false, null);
            } else throw bad("summary.compare.type 은 plan(계획 대비), minus(다른 자료를 뺀 잔량·재고), previous(전기 대비) 중 하나입니다.");
        }
        boolean share = block.path("share").asBoolean(false);
        Integer top = block.hasNonNull("top") ? Integer.valueOf(block.get("top").asInt(0)) : null;
        if (top != null && (top < 1 || top > 100)) throw bad("summary.top 은 1~100 입니다.");
        return new Definition(key, "summary", title, keywords, List.of(), null, null, List.of(), new Summary(entity, lines, groups, values, filters, chart, compare, share, top, block.path("cumulative").asBoolean(false)), null, null, List.of(), List.of(), List.of(), null, null, null, null);
    }

    /** What a header total adds up: "amount" = that number of the first table of lines, "materials.amount" = of the table named materials. Null when there is none. */
    public static Object[] sumTarget(Lines lines, List<LineSet> moreLines, String sum) {
        int dot = sum.indexOf('.');
        String set = dot < 0 ? "lines" : sum.substring(0, dot), name = dot < 0 ? sum : sum.substring(dot + 1);
        List<Field> among = set.equals("lines") ? (lines == null ? List.of() : lines.fields()) : moreLines.stream().filter(more -> more.name().equals(set)).findFirst().map(LineSet::fields).orElse(List.of());
        for (Field field : among) if (field.name().equals(name) && field.type().equals("number")) return new Object[] {set, field};
        return null;
    }

    /** A field of the source by name: a line field when lines are gathered, else (or also) a header field. */
    public static Field sourceField(Definition source, String name, boolean lines) {
        if (lines && source.lines() != null)
            for (Field field : source.lines().fields()) if (field.name().equals(name)) return field;
        return source.field(name);
    }
    private static String sourceNames(Definition source, boolean lines) {
        List<String> out = new ArrayList<>();
        for (Field field : source.fields()) out.add(field.name());
        if (lines && source.lines() != null) for (Field field : source.lines().fields()) out.add(field.name());
        if (source.status() != null) out.add("status");
        return out.toString();
    }
    private static String sourceNumbers(Definition source, boolean lines) {
        List<String> out = new ArrayList<>();
        if (lines && source.lines() != null) { for (Field field : source.lines().fields()) if (field.type().equals("number")) out.add(field.name()); }
        else for (Field field : source.fields()) if (field.type().equals("number")) out.add(field.name());
        return out.toString();
    }
    /** The target's field shown before its name: the definition's choice, or the target's first field when that is a code or number of its own. */
    public String codeField(Ref ref) {
        if (ref.code() != null) return ref.code();
        Stored target = find(ref.entity());
        if (target == null || target.definition().fields().isEmpty()) return null;
        Field first = target.definition().fields().get(0);
        return !first.name().equals(ref.label()) && (first.type().equals("text") || first.type().equals("serial")) ? first.name() : null;
    }

    /** above: the fields of the record the lines belong to (a line's condition may look at them); null for the record's own fields. */
    private List<Field> fields(String key, JsonNode list, String where, boolean header, boolean checkTargets, List<Field> above) {
        if (list == null || !list.isArray() || list.isEmpty() || list.size() > 30) throw bad(where + " 는 1~30개의 항목 목록이어야 합니다.");
        List<Field> fields = new ArrayList<>();
        Set<String> names = new LinkedHashSet<>();
        for (JsonNode item : list) {
            String name = text(item, "name"), label = text(item, "label"), type = item.hasNonNull("type") ? text(item, "type") : "text";
            if (!name.matches(NAME)) throw bad("항목 name '" + name + "' 은(는) 영문 camelCase 여야 합니다.");
            if (RESERVED.contains(name)) throw bad("항목 이름 " + name + " 은(는) 프레임워크가 쓰는 이름입니다. 다른 이름을 쓰세요" + (name.equals("status") ? " (상태는 definition.status 로 정의합니다)." : "."));
            if (!names.add(name)) throw bad("항목 " + name + " 이(가) 두 번 나옵니다.");
            if (label.isEmpty() || label.length() > 30) throw bad("항목 " + name + " 에 label(화면에 보이는 이름)이 필요합니다.");
            if (!FIELD_TYPES.contains(type)) throw bad("항목 " + name + " 의 type 은 " + FIELD_TYPES + " 중 하나여야 합니다.");
            String codeGroup = null, prefix = null, formula = null, sum = null;
            Ref ref = null;
            Map<String, String> fill = null;
            if (type.equals("code")) {
                codeGroup = text(item, "codeGroup");
                if (!codeGroup.matches("[A-Za-z0-9_-]{1,50}")) throw bad("항목 " + name + " (code) 에 codeGroup 이 필요합니다.");
                if (checkTargets && !declared.get().containsKey(codeGroup) && jdbc.queryForObject("SELECT COUNT(*) FROM sys_code_groups WHERE group_code = ?", Integer.class, codeGroup) == 0)
                    throw bad("항목 " + name + ": 공통 코드 그룹 " + codeGroup + " 이(가) 없습니다. 새 그룹이면 codeGroups 에 선언한다: {\"code\": \"" + codeGroup + "\", \"name\": \"<그룹 이름>\", \"values\": [{\"code\": \"<코드>\", \"name\": \"<이름>\"}]}.");
            }
            if (type.equals("user") && !header) throw bad("user(등록한 사람) 는 머리 항목에만 씁니다 (" + name + ").");
            if (type.equals("serial")) {
                if (!header) throw bad("serial 은 머리 항목에만 씁니다 (" + name + ").");
                prefix = text(item, "prefix");
                if (!prefix.matches("[A-Z]{1,6}")) throw bad("항목 " + name + " (serial) 에 prefix(영문 대문자 1~6자)가 필요합니다.");
            }
            Stored target = null;
            if (type.equals("ref")) {
                JsonNode to = item.get("ref");
                String entity = to == null ? "" : text(to, "entity"), shown = to == null ? "" : text(to, "label");
                if (!entity.matches(KEY)) throw bad("항목 " + name + " (ref) 에는 \"ref\": {\"entity\": \"<고를 자료의 key>\", \"label\": \"<그 자료에서 보여 줄 항목 name>\"} 이 필요합니다.");
                boolean toLine = to != null && to.path("line").asBoolean(false);
                if (checkTargets && !entity.equals(key)) {
                    target = find(entity);
                    if (target == null) throw bad("항목 " + name + ": 가리키는 자료 " + entity + " 의 정의가 없습니다. 먼저 그 자료를 만들어야 합니다.");
                    if (toLine && target.definition().lines() == null) throw bad("항목 " + name + ": ref.line 은 줄 표가 있는 자료의 줄을 가리킬 때 씁니다 (" + entity + " 에는 줄 표가 없습니다).");
                    // The target's field may be named by its name or by the label people see ("사원명"): either way it is stored by name.
                    shown = toLine ? named(target.definition().lines().fields(), shown, "항목 " + name + " 의 ref.label (" + entity + " 의 줄 항목)") : named(target.definition(), shown, "항목 " + name + " 의 ref.label", entity);
                }
                if (!shown.matches(NAME)) throw bad("항목 " + name + " 의 ref.label 은 " + entity + " 의 항목 name(영문)입니다 (받은 값: " + shown + ").");
                List<String> columns = null;
                if (to.hasNonNull("columns") && to.get("columns").isArray()) {
                    columns = new ArrayList<>();
                    for (JsonNode column : to.get("columns"))
                        columns.add(target == null ? column.asString() : named(target.definition(), column.asString(), "항목 " + name + " 의 ref.columns", entity));
                    if (columns.isEmpty() || columns.size() > 8) throw bad("항목 " + name + " 의 ref.columns 는 1~8개여야 합니다.");
                }
                String code = to.hasNonNull("code") ? text(to, "code") : null;
                if (code != null && target != null) code = named(target.definition(), code, "항목 " + name + " 의 ref.code", entity);
                String within = null, withinTarget = null;
                if (toLine && to.hasNonNull("within")) {
                    // {"field", "target"} as written; a stored definition writes it out as "within" and "withinTarget"
                    within = to.get("within").isObject() ? text(to.get("within"), "field") : to.get("within").asString();
                    withinTarget = to.get("within").isObject() ? text(to.get("within"), "target") : text(to, "withinTarget");
                    if (target != null) withinTarget = named(target.definition(), withinTarget, "항목 " + name + " 의 ref.within.target", entity);
                    if (within.isEmpty() || withinTarget.isEmpty()) throw bad("항목 " + name + " 의 ref.within 은 {\"field\": \"<이 자료의 항목>\", \"target\": \"<" + entity + " 의 위쪽 항목>\"} 입니다. 예: 같은 품목의 공정만 = {\"field\": \"itemId\", \"target\": \"itemId\"}");
                } else if (!toLine && to != null && to.hasNonNull("within")) throw bad("항목 " + name + ": ref.within 은 ref.line 이 true 일 때 씁니다.");
                ref = new Ref(entity, shown, columns, code, toLine, within, withinTarget);
                if (toLine && item.hasNonNull("fill")) throw bad("항목 " + name + ": 줄을 가리키는 ref 에는 fill 을 쓰지 않습니다.");
                if (item.hasNonNull("fill") && item.get("fill").isObject()) {
                    fill = new LinkedHashMap<>();
                    for (Map.Entry<String, JsonNode> entry : item.get("fill").properties())
                        fill.put(entry.getKey(), target == null ? entry.getValue().asString() : named(target.definition(), entry.getValue().asString(), "항목 " + name + " 의 fill", entity));
                }
            }
            if (item.hasNonNull("formula")) {
                if (!type.equals("number")) throw bad("formula 는 숫자 항목에만 씁니다 (" + name + ").");
                formula = text(item, "formula");
            }
            if (item.hasNonNull("sum")) {
                if (!type.equals("number") || !header) throw bad("sum 은 머리의 숫자 항목에만 씁니다 (" + name + ").");
                sum = text(item, "sum");
            }
            if (type.equals("memo") && !header) throw bad("memo(긴 글)는 줄 표의 항목으로 못 씁니다 (" + name + "). 줄 표에는 text 를 씁니다.");
            // A yes/no is never empty (an unticked box is "no"), so it cannot be required.
            boolean required = item.path("required").asBoolean(false) && !type.equals("yesno") && !type.equals("user");     // (who registered it is always there)
            if (required && (formula != null || sum != null || type.equals("serial"))) throw bad("항목 " + name + " 은(는) 서버가 계산하므로 required 를 주지 않습니다.");
            Double min = item.hasNonNull("min") && item.get("min").isNumber() ? Double.valueOf(item.get("min").asDouble()) : null;
            Double max = item.hasNonNull("max") && item.get("max").isNumber() ? Double.valueOf(item.get("max").asDouble()) : null;
            if ((item.hasNonNull("min") && min == null) || (item.hasNonNull("max") && max == null)) throw bad("항목 " + name + " 의 min, max 는 숫자여야 합니다.");
            if ((min != null || max != null) && (!type.equals("number") || formula != null || sum != null)) throw bad("min, max 는 직접 입력하는 숫자 항목에만 씁니다 (" + name + ").");
            if (min != null && max != null && min > max) throw bad("항목 " + name + " 의 min 이 max 보다 큽니다.");
            Integer decimals = null;
            if (item.hasNonNull("decimals")) {
                if (!type.equals("number")) throw bad("decimals 는 숫자 항목에만 씁니다 (" + name + ").");
                if (!item.get("decimals").isIntegralNumber() || item.get("decimals").asInt() < 0 || item.get("decimals").asInt() > 6) throw bad("항목 " + name + " 의 decimals 는 0~6 의 정수입니다.");
                decimals = item.get("decimals").asInt();
            }
            boolean unique = item.path("unique").asBoolean(false);
            if (unique && (type.equals("yesno") || type.equals("memo"))) throw bad("unique 는 yesno, memo 항목에 못 씁니다 (" + name + ").");
            // in a table of lines, unique means: the same value twice in one record's lines is refused (a part listed twice in a BOM)
            if (unique && (formula != null || sum != null)) throw bad("unique 는 직접 입력하는 항목에만 씁니다 (" + name + ").");
            String pick = item.hasNonNull("pick") ? text(item, "pick") : null;
            if (pick != null && !(type.equals("code") || type.equals("ref"))) throw bad("pick 은 고르는 항목(code, ref)에만 씁니다 (" + name + ").");
            if ("popup".equals(pick)) pick = "search";          // an older word for the same thing
            if (pick != null && !PICKS.contains(pick)) throw bad("항목 " + name + " 의 pick 은 dropdown 또는 search 입니다.");
            Condition showWhen = condition(item, "showWhen", name), requiredWhen = condition(item, "requiredWhen", name), lockWhen = condition(item, "lockWhen", name);
            if ((showWhen != null || requiredWhen != null || lockWhen != null) && (formula != null || sum != null || type.equals("serial"))) throw bad("항목 " + name + " 은(는) 서버가 계산하므로 showWhen, requiredWhen, lockWhen 을 주지 않습니다.");
            if (requiredWhen != null && type.equals("yesno")) throw bad("yesno 항목에는 requiredWhen 을 못 씁니다 (" + name + ").");
            if (requiredWhen != null && required) throw bad("항목 " + name + ": 언제나 필수(required)이면 requiredWhen 은 적지 않습니다. 조건이 맞을 때만 필수면 required 를 빼세요.");
            if (unique && showWhen != null) throw bad("unique 항목에는 showWhen 을 못 씁니다 (" + name + ").");
            fields.add(new Field(name, label, type, required, item.path("search").asBoolean(false), codeGroup, ref, prefix, formula, sum, fill, min, max, unique, pick, decimals, showWhen, requiredWhen, lockWhen));
        }
        for (Field field : fields)
            if (field.ref() != null && field.ref().within() != null) {
                Field mine = fields.stream().filter(other -> other.name().equals(field.ref().within())).findFirst().orElse(above == null ? null : above.stream().filter(other -> other.name().equals(field.ref().within())).findFirst().orElse(null));
                if (mine == null) throw bad("항목 " + field.name() + " 의 ref.within.field " + field.ref().within() + " 이(가) 이 자료에 없습니다 (같은 표" + (above == null ? "" : "나 위쪽") + "의 항목 name).");
            }
        for (Field field : fields)
            for (Condition when : new Condition[] {field.showWhen(), field.requiredWhen(), field.lockWhen()}) {
                if (when == null) continue;
                Field on = fields.stream().filter(other -> other.name().equals(when.field())).findFirst().orElse(above == null ? null : above.stream().filter(other -> other.name().equals(when.field())).findFirst().orElse(null));
                if (on == null || on == field) throw bad("항목 " + field.name() + " 의 조건(showWhen 등)이 보는 항목 " + when.field() + " 이(가) 없습니다. 같은 표" + (above == null ? "" : "나 위쪽") + "의 다른 항목 name 을 적습니다: " + names(fields));
                if (on.formula() != null || on.sum() != null || on.type().equals("serial") || on.type().equals("memo")) throw bad("항목 " + field.name() + " 의 조건은 직접 입력하거나 고르는 항목을 봅니다 (" + when.field() + " 은(는) 안 됩니다).");
                if (on.showWhen() != null && on.showWhen().field().equals(field.name())) throw bad("항목 " + field.name() + " 와(과) " + on.name() + " 이(가) 서로를 조건으로 봅니다.");
                if (on.type().equals("ref") && when.is().stream().anyMatch(value -> !value.isEmpty()))
                    throw bad("항목 " + field.name() + " 의 조건: ref 항목 " + on.name() + " 은(는) 고른 자료의 번호를 담으므로 " + when.is() + " 같은 값과 맞을 수 없습니다. 비었는지만 볼 수 있습니다 (is: [\"\"]). "
                            + "고른 자료의 항목에 따라 달라지는 묶음 번호는 ledger.lotWhen 이 정하므로 ledger.lot 항목에는 조건을 달지 않습니다.");
                if (on.type().equals("yesno")) for (String value : when.is()) if (!value.equals("true") && !value.equals("false")) throw bad("항목 " + field.name() + ": yesno 항목 " + on.name() + " 을(를) 보는 조건의 is 는 [\"true\"] 또는 [\"false\"] 입니다.");
                if (checkTargets && on.type().equals("code"))
                    for (String value : when.is())
                        if (!value.isEmpty() && !declared.get().getOrDefault(on.codeGroup(), List.of()).contains(value) && jdbc.queryForObject("SELECT COUNT(*) FROM sys_codes WHERE group_code = ? AND code = ?", Integer.class, on.codeGroup(), value) == 0)
                            throw bad("항목 " + field.name() + " 의 조건: 공통 코드 그룹 " + on.codeGroup() + " 에 코드 " + value + " 이(가) 없습니다. is 에는 코드 이름이 아니라 코드를 적습니다. 있는 코드: "
                                    + jdbc.queryForList("SELECT code || ' ' || code_name FROM sys_codes WHERE group_code = ? ORDER BY sort_order, code", String.class, on.codeGroup()));
            }
        for (Field field : fields) {
            if (field.formula() != null) {
                Map<String, Double> probe = new LinkedHashMap<>();
                for (Field other : fields) if (other.type().equals("number") && other != field) probe.put(other.name(), 1.0);
                try { Formula.evaluate(field.formula(), probe); }
                catch (IllegalArgumentException error) { throw bad("항목 " + field.name() + " 의 formula: " + error.getMessage() + " (같은 줄의 숫자 항목만 쓸 수 있습니다: " + probe.keySet() + ")"); }
            }
            if (field.fill() != null)
                for (String into : field.fill().keySet())
                    if (fields.stream().noneMatch(other -> other.name().equals(into))) throw bad("항목 " + field.name() + " 의 fill 대상 " + into + " 이(가) 같은 줄에 없습니다.");
        }
        return fields;
    }

    private List<CodeGroup> codeGroups(JsonNode list) {
        List<CodeGroup> out = new ArrayList<>();
        if (list == null || !list.isArray()) return out;
        for (JsonNode item : list) {
            known(item, "codeGroups", Set.of("code", "name", "values"));
            String code = text(item, "code"), name = text(item, "name");
            if (!code.matches("[A-Z][A-Z0-9_]{1,49}") || name.isEmpty()) throw bad("codeGroups 의 code 는 영문 대문자·숫자·_ (예: UNIT), name 은 그룹 이름입니다.");
            List<CodeValue> values = new ArrayList<>();
            Set<String> seen = new LinkedHashSet<>();
            for (JsonNode value : item.path("values")) {
                String one = text(value, "code"), label = text(value, "name");
                if (!one.matches("[A-Za-z0-9_-]{1,50}") || label.isEmpty() || !seen.add(one)) throw bad("codeGroups." + code + ".values 는 {code(영문·숫자), name} 목록이고 code 가 겹치면 안 됩니다.");
                values.add(new CodeValue(one, label));
            }
            if (values.isEmpty()) throw bad("codeGroups." + code + " 에 values 가 하나 이상 있어야 합니다.");
            out.add(new CodeGroup(code, name, values));
        }
        return out;
    }
    /** The groups a definition declares that are not there yet are made, with their values (a group already there is left as it is). */
    public void ensureCodes(Definition definition) {
        for (CodeGroup group : definition.codeGroups()) {
            if (jdbc.update("INSERT INTO sys_code_groups (group_code, group_name) VALUES (?, ?) ON CONFLICT (group_code) DO NOTHING", group.code(), group.name()) == 0) continue;
            int order = 0;
            for (CodeValue value : group.values())
                jdbc.update("INSERT INTO sys_codes (group_code, code, code_name, sort_order) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING", group.code(), value.code(), value.name(), ++order);
        }
    }
    private Lock lock(JsonNode node, List<Field> fields) {
        if (node == null || node.isNull()) return null;
        known(node, "lock", Set.of("group", "date"));
        String group = text(node, "group").trim(), date = text(node, "date");
        if (group.isEmpty() || group.length() > 20) throw bad("lock.group 은 잠금 묶음의 이름입니다 (1~20자, 예: 수불).");
        if (fields.stream().noneMatch(field -> field.name().equals(date) && field.type().equals("date"))) throw bad("lock.date 는 이 자료의 날짜 항목 name 입니다 (" + date + ").");
        return new Lock(group, date);
    }
    private List<Lookup> lookups(String key, JsonNode list, List<Field> fields, boolean checkTargets) {
        List<Lookup> out = new ArrayList<>();
        if (list == null || !list.isArray()) return out;
        for (JsonNode item : list) {
            known(item, "lookups", Set.of("from", "match", "at", "set"));
            String from = text(item, "from"), at = item.hasNonNull("at") ? text(item, "at") : null;
            Map<String, String> match = new LinkedHashMap<>(), set = new LinkedHashMap<>();
            for (Map.Entry<String, JsonNode> entry : item.path("match").properties()) match.put(entry.getKey(), entry.getValue().asString());
            for (Map.Entry<String, JsonNode> entry : item.path("set").properties()) set.put(entry.getKey(), entry.getValue().asString());
            if (match.isEmpty() || set.isEmpty()) throw bad("lookups 는 {from: <기준 정보 key>, match: {<그 자료의 항목>: <이 자료의 항목>}, at: <이 자료의 날짜 항목>, set: {<이 자료의 항목>: <그 자료의 항목>}} 모양입니다.");
            for (String mine : match.values()) if (fields.stream().noneMatch(field -> field.name().equals(mine))) throw bad("lookups.match: 이 자료에 " + mine + " 항목이 없습니다.");
            for (String mine : set.keySet()) if (fields.stream().noneMatch(field -> field.name().equals(mine))) throw bad("lookups.set: 이 자료에 " + mine + " 항목이 없습니다.");
            if (at != null && fields.stream().noneMatch(field -> field.name().equals(at) && field.type().equals("date"))) throw bad("lookups.at 은 이 자료의 날짜 항목 name 입니다 (" + at + ").");
            if (checkTargets) {
                Stored master = find(from);
                if (master == null || master.definition().fields().isEmpty()) throw bad("lookups.from: 기준 정보 " + from + " 의 정의가 없습니다.");
                for (String theirs : match.keySet()) if (master.definition().field(theirs) == null) throw bad("lookups.match: " + from + " 에 " + theirs + " 항목이 없습니다. 있는 항목: " + master.definition().fields().stream().map(Field::name).toList());
                for (String theirs : set.values()) if (master.definition().field(theirs) == null) throw bad("lookups.set: " + from + " 에 " + theirs + " 항목이 없습니다. 있는 항목: " + master.definition().fields().stream().map(Field::name).toList());
            }
            out.add(new Lookup(from, match, at, set));
        }
        return out;
    }
    /** follows: the ref field of a later stage that points at the stage before it (its records come only from there). */
    private String follows(JsonNode node, List<Field> fields) {
        if (!node.hasNonNull("follows")) return null;
        String name = text(node, "follows");
        Field field = fields.stream().filter(candidate -> candidate.name().equals(name)).findFirst().orElse(null);
        if (field == null || field.ref() == null) throw bad("follows 는 이 자료의 위쪽 항목 중 앞 단계 자료를 가리키는 ref 항목 name 입니다 (" + name + ").");
        if (field.required()) throw bad("follows 항목(" + name + ")은 required 로 두지 않는다: 기타 화면에서 앞 단계 없이 등록할 때 비어 있다. 이어받기로 생기는 자료에는 언제나 채워진다.");
        return name;
    }
    private Status status(JsonNode node) {
        if (node == null || node.isNull()) return null;
        List<StatusValue> values = new ArrayList<>();
        Set<String> codes = new LinkedHashSet<>();
        if (node.has("values") && node.get("values").isArray())
            for (JsonNode value : node.get("values")) {
                String code = text(value, "code"), label = text(value, "label");
                if (!code.matches("[A-Z][A-Z0-9_]{0,29}") || label.isEmpty() || !codes.add(code)) throw bad("status.values 는 {code(영문 대문자), label} 목록이어야 하고 code 가 겹치면 안 됩니다.");
                values.add(new StatusValue(code, label));
            }
        if (values.isEmpty()) throw bad("status.values 가 필요합니다.");
        String initial = text(node, "initial");
        if (!codes.contains(initial)) throw bad("status.initial 은 values 의 code 중 하나여야 합니다.");
        List<Action> actions = new ArrayList<>();
        if (node.has("actions") && node.get("actions").isArray())
            for (JsonNode action : node.get("actions")) {
                String name = camel(text(action, "name")), label = text(action, "label"), to = text(action, "to");
                List<String> from = new ArrayList<>();
                if (action.has("from") && action.get("from").isArray()) for (JsonNode code : action.get("from")) from.add(code.asString());
                String said = "status.actions 의 " + (name.isEmpty() ? "동작" : name) + ": ";
                if (!name.matches("[a-z][A-Za-z0-9]{0,29}")) throw bad(said + "name 은 영문 소문자로 시작하는 영문·숫자 30자 이내입니다 (예: confirm, finishEarly).");
                if (name.equals("delete") || name.equals("update")) throw bad(said + "delete, update 는 이름으로 쓸 수 없습니다 (삭제·수정은 화면이 이미 합니다).");
                if (label.isEmpty()) throw bad(said + "label (버튼에 보일 말)이 필요합니다.");
                if (!codes.contains(to)) throw bad(said + "to 는 status.values 의 code 하나입니다 (" + to + " 은(는) 없습니다). 있는 code: " + codes);
                if (from.isEmpty() || !codes.containsAll(from)) throw bad(said + "from 은 status.values 의 code 목록입니다 (" + from + "). 있는 code: " + codes);
                actions.add(new Action(name, label, from, to, action.path("separate").asBoolean(false)));
            }
        List<String> locked = new ArrayList<>();
        if (node.has("locked") && node.get("locked").isArray()) for (JsonNode code : node.get("locked")) locked.add(code.asString());
        if (!codes.containsAll(locked)) throw bad("status.locked 는 values 의 code 여야 합니다.");
        List<String> closed = new ArrayList<>();
        if (node.has("closed") && node.get("closed").isArray()) for (JsonNode code : node.get("closed")) closed.add(code.asString());
        if (!codes.containsAll(closed)) throw bad("status.closed 는 values 의 code 여야 합니다.");
        if (closed.contains(initial)) throw bad("status.closed 에 처음 상태(initial)를 넣지 않습니다: 처음부터 끝난 자료가 됩니다.");
        return new Status(initial, values, actions, locked, closed);
    }

    private List<Rule> rules(String key, JsonNode list, Status status, boolean checkTargets) {
        List<Rule> rules = new ArrayList<>();
        if (list == null || !list.isArray()) return rules;
        for (JsonNode item : list) {
            String type = text(item, "type"), action = text(item, "action"), entity = text(item, "entity"), field = text(item, "field"), message = text(item, "message");
            if (!type.equals("blockWhenReferenced")) throw bad("rules 의 type 은 blockWhenReferenced 입니다.");
            boolean known = action.equals("delete") || action.equals("update") || (status != null && status.actions().stream().anyMatch(candidate -> candidate.name().equals(action)));
            if (!known) throw bad("rule 의 action 은 delete, update 또는 status.actions 의 name 이어야 합니다 (" + action + ").");
            if (!entity.matches(KEY) || !field.matches(NAME) || message.isEmpty()) throw bad("rule 에는 entity, field, message 가 필요합니다.");
            if (checkTargets) {
                Stored other = find(entity);
                if (other == null) throw bad("rule: 자료 " + entity + " 의 정의가 없습니다. 그 자료를 먼저 만든 뒤 규칙을 추가하세요.");
                Field pointer = other.definition().field(field);
                // (the pointing field may sit in the other entity's lines: an instruction that gathers several orders points at each from its lines)
                if (pointer == null) for (LineSet set : other.definition().lineSets()) for (Field line : set.fields()) if (pointer == null && line.name().equals(field)) pointer = line;
                if (pointer == null || pointer.ref() == null || !pointer.ref().entity().equals(key))
                    throw bad("rule: " + entity + "." + field + " 은(는) 이 자료(" + key + ")를 가리키는 ref 항목이어야 합니다.");
            }
            rules.add(new Rule(type, action, entity, field, message));
        }
        return rules;
    }

    private static Field among(List<Field> fields, Lines lines, String name, boolean inLines) {
        if (inLines && lines != null) for (Field field : lines.fields()) if (field.name().equals(name)) return field;
        for (Field field : fields) if (field.name().equals(name)) return field;
        return null;
    }

    private List<Check> checks(JsonNode list, List<Field> fields, Lines lines) {
        List<Check> out = new ArrayList<>();
        if (list == null || !list.isArray()) return out;
        for (JsonNode item : list) {
            String left = text(item, "left"), op = text(item, "op"), right = text(item, "right"), message = text(item, "message");
            boolean inLines = item.path("lines").asBoolean(false);
            if (inLines && lines == null) throw bad("checks 의 lines 는 줄 표가 있을 때만 씁니다.");
            List<Field> scope = inLines ? lines.fields() : fields;
            Field first = scope.stream().filter(field -> field.name().equals(left)).findFirst().orElse(null);
            Field second = right.equals("today") ? null : scope.stream().filter(field -> field.name().equals(right)).findFirst().orElse(null);
            if (!COMPARISONS.contains(op)) throw bad("checks 의 op 는 " + COMPARISONS + " 중 하나입니다.");
            if (first == null || (second == null && !right.equals("today")))
                throw bad("checks 의 left, right 는 " + (inLines ? "줄 표" : "위쪽") + " 항목의 name 입니다 (right 는 today 도 됨). 있는 항목: " + names(scope));
            String kind = first.type();
            if (!(kind.equals("date") || kind.equals("number") || kind.equals("time")) || (second != null && !second.type().equals(kind)) || (second == null && !kind.equals("date")))
                throw bad("checks 는 날짜끼리, 시각끼리 또는 숫자끼리 견줍니다 (" + left + " " + op + " " + right + ").");
            if (message.isEmpty()) throw bad("checks 에는 어겼을 때 보여 줄 message 가 필요합니다.");
            out.add(new Check(left, op, right, inLines, message));
        }
        return out;
    }

    private List<Limit> limits(String key, JsonNode list, List<Field> fields, Lines lines, boolean checkTargets) {
        List<Limit> out = new ArrayList<>();
        if (list == null || !list.isArray()) return out;
        for (JsonNode item : list) {
            String field = text(item, "field"), entity = text(item, "entity"), entityField = text(item, "entityField"), message = text(item, "message");
            boolean inLines = item.path("lines").asBoolean(false), entityLines = item.path("entityLines").asBoolean(false);
            List<String> by = new ArrayList<>(), entityBy = new ArrayList<>(), ignore = new ArrayList<>(), entityIgnore = new ArrayList<>();
            for (JsonNode name : item.path("by")) by.add(name.asString());
            for (JsonNode name : item.path("entityBy")) entityBy.add(name.asString());
            for (JsonNode name : item.path("ignore")) ignore.add(name.asString());
            for (JsonNode name : item.path("entityIgnore")) entityIgnore.add(name.asString());
            if (inLines && lines == null) throw bad("limits 의 lines 는 줄 표가 있을 때만 씁니다.");
            boolean once = field.isEmpty() && entityField.isEmpty(), counted = field.isEmpty();
            if (once && entityLines) throw bad("한 번만 이어지는 limits (field·entityField 없음)는 앞 자료 한 건마다입니다: entityLines 를 적지 않습니다.");
            Field number = counted ? null : among(fields, lines, field, inLines);
            if (!counted && (number == null || !number.type().equals("number")))
                throw bad("limits.field 는 이 자료의 숫자 항목입니다 (" + field + "). 수량 없이 앞 자료 한 건에 한 번만 이어지면 field 와 entityField 를 둘 다 적지 않습니다.");
            if (by.isEmpty() || by.size() > 3 || by.size() != entityBy.size()) throw bad("limits 의 by 와 entityBy 는 같은 개수(1~3)로, 서로 짝이 되는 항목을 같은 순서로 적습니다.");
            if (message.isEmpty()) throw bad("limits 에는 넘었을 때 보여 줄 message 가 필요합니다.");
            for (String name : by) if (among(fields, lines, name, inLines) == null) throw bad("limits.by: 이 자료에 " + name + " 항목이 없습니다.");
            if (checkTargets) {
                Stored other = entity.matches(KEY) && !entity.equals(key) ? find(entity) : null;
                if (other == null || other.definition().summary() != null || other.definition().dashboard() != null) throw bad("limits.entity: 한도가 되는 자료 " + entity + " 의 정의가 없습니다.");
                if (entityLines && other.definition().lines() == null) throw bad("limits.entityLines: " + entity + " 에는 줄 표가 없습니다.");
                Field cap = once ? null : sourceField(other.definition(), entityField, entityLines);
                if (!once && (cap == null || !cap.type().equals("number"))) throw bad("limits.entityField 는 " + entity + " 의 숫자 항목입니다: " + sourceNumbers(other.definition(), entityLines));
                for (int index = 0; index < by.size(); index++) {
                    Field mine = among(fields, lines, by.get(index), inLines);
                    String theirName = entityBy.get(index);
                    Field theirs = theirName.equals("id") ? null : sourceField(other.definition(), theirName, entityLines);
                    boolean same = theirName.equals("id") ? mine.ref() != null && mine.ref().entity().equals(entity)
                            : theirs != null && theirs.type().equals(mine.type()) && (mine.ref() == null || (theirs.ref() != null && theirs.ref().entity().equals(mine.ref().entity())));
                    if (!same) throw bad("limits: " + by.get(index) + " 와(과) " + entity + "." + theirName + " 은(는) 짝이 맞지 않습니다 (같은 자료를 고르는 항목끼리, 또는 그 자료를 가리키는 항목 ↔ id). " + entity + " 의 항목: " + sourceNames(other.definition(), entityLines) + ", id");
                }
            }
            out.add(new Limit(field, inLines, by, entity, entityField, entityLines, entityBy, ignore, entityIgnore, message));
        }
        return out;
    }

    /** A field of another entity, given by its name or by its label: returns the name, or refuses listing both for every field. */
    private static String named(Definition target, String given, String where, String entity) {
        for (Field field : target.fields()) if (field.name().equals(given)) return field.name();
        for (Field field : target.fields()) if (field.label().replace(" ", "").equals(given.replace(" ", ""))) return field.name();
        throw bad(where + ": " + entity + " 에 " + given + " 항목이 없습니다. 있는 항목(name=화면 이름): "
                + target.fields().stream().map(field -> field.name() + "=" + field.label()).toList() + ". name 을 적습니다.");
    }

    private static void fits(String key, Field into, String from, Field source, String entity) {
        if (into == null) return;
        boolean same = from.equals("today") ? into.type().equals("date")
                : from.equals("id") ? into.ref() != null && into.ref().entity().equals(key)
                : source != null && (source.type().equals(into.type()) || (source.type().equals("serial") && into.type().equals("text")))
                    && (into.ref() == null || (source.ref() != null && source.ref().entity().equals(into.ref().entity())))
                    && (into.codeGroup() == null || into.codeGroup().equals(source.codeGroup()));
        if (!same) throw bad("effects.create.set: " + entity + "." + into.name() + "(" + into.label() + ", " + into.type() + (into.ref() != null ? "→" + into.ref().entity() : "") + ") 에 "
                + from + (source != null ? "(" + source.label() + ", " + source.type() + (source.ref() != null ? "→" + source.ref().entity() : "") + ")" : "") + " 을(를) 넣을 수 없습니다. 같은 종류끼리만 옮길 수 있습니다 (같은 자료를 고르는 항목끼리, 날짜는 날짜끼리).");
    }

    private List<Effect> effects(String key, JsonNode list, List<Field> fields, Lines lines, Status status, boolean checkTargets) {
        List<Effect> out = new ArrayList<>();
        if (list == null || !list.isArray()) return out;
        for (JsonNode item : list) {
            String on = text(item, "on");
            if (!on.equals("create") && (status == null || status.actions().stream().noneMatch(action -> action.name().equals(on))))
                throw bad("effects.on 은 create(등록할 때) 또는 status.actions 의 name 입니다 (" + on + ").");
            if (item.hasNonNull("cascade")) {
                if (item.hasNonNull("create") || item.hasNonNull("act") || item.hasNonNull("fill") || item.hasNonNull("expand")) throw bad("effects 에는 create, act, fill, expand, cascade 중 하나만 적습니다.");
                if (on.equals("create")) throw bad("effects.cascade 는 상태 동작(on 이 action name)에만 씁니다: 이 자료가 그 동작을 하면 이 자료를 가리키는 자료들도 그 동작을 한다.");
                JsonNode block = item.get("cascade");
                known(block, "effects.cascade", Set.of("entity", "via", "action"));
                String entity = text(block, "entity"), via = text(block, "via"), action = text(block, "action");
                if (checkTargets) {
                    Stored other = find(entity);
                    if (other == null) throw bad("effects.cascade.entity: " + entity + " 라는 자료가 없습니다.");
                    Field pointer = other.definition().field(via);
                    if (pointer == null || pointer.ref() == null || !pointer.ref().entity().equals(key))
                        throw bad("effects.cascade.via 는 " + entity + " 의 항목 중 이 자료(" + key + ")를 가리키는 ref 항목 name 입니다" + (other.definition().fields().stream().anyMatch(field -> field.ref() != null && field.ref().entity().equals(key))
                                ? ": " + other.definition().fields().stream().filter(field -> field.ref() != null && field.ref().entity().equals(key)).map(Field::name).toList() : " (그런 항목이 없습니다)") + ".");
                    if (other.definition().status() == null || other.definition().status().actions().stream().noneMatch(candidate -> candidate.name().equals(action)))
                        throw bad("effects.cascade.action 은 " + entity + " 의 status.actions name 입니다" + (other.definition().status() != null ? ": " + other.definition().status().actions().stream().map(Action::name).toList() : " (그 자료에 상태가 없습니다)")
                                + ". 그 동작이 아직 없으면 이 정의를 쓰지 말고 steps 로 나눈다: 먼저 " + entity + " 에 그 상태와 동작(예: 마감, 마감취소)을 넣는 단계, 다음에 이 자료에 cascade 를 넣는 단계.");
                }
                out.add(new Effect(on, null, null, null, null, new Cascade(entity, via, action)));
                continue;
            }
            if (item.hasNonNull("expand")) {
                if (item.hasNonNull("create") || item.hasNonNull("act") || item.hasNonNull("fill")) throw bad("effects 에는 create, act, fill, expand 중 하나만 적습니다.");
                JsonNode block = item.get("expand");
                String from = text(block, "from"), into = text(block, "into");
                Map<String, String> match = new LinkedHashMap<>(), set = new LinkedHashMap<>();
                for (Map.Entry<String, JsonNode> entry : block.path("match").properties()) match.put(entry.getKey(), entry.getValue().asString());
                for (Map.Entry<String, JsonNode> entry : block.path("set").properties()) set.put(entry.getKey(), entry.getValue().asString());
                JsonNode quantity = block.path("quantity");       // {"into", "line", "times"} as written; quantityInto / quantityLine / quantityTimes as stored
                String qInto = quantity.isObject() ? text(quantity, "into") : text(block, "quantityInto"), qLine = quantity.isObject() ? text(quantity, "line") : text(block, "quantityLine");
                String qTimes = quantity.isObject() ? (quantity.hasNonNull("times") ? text(quantity, "times") : null) : (block.hasNonNull("quantityTimes") ? text(block, "quantityTimes") : null);
                if (match.isEmpty() || qInto.isEmpty() || qLine.isEmpty())
                    throw bad("effects.expand 는 {\"from\": \"<기준 정보 key>\", \"match\": {\"<그 기준 정보의 위쪽 항목>\": \"<이 자료의 항목>\"}, \"into\": \"<만들 자료 key>\", \"set\": {...}, \"quantity\": {\"into\": \"<만들 자료의 수량 항목>\", \"line\": \"<기준 정보 줄의 수량 항목>\", \"times\": \"<이 자료의 수량 항목>\"}} 입니다.");
                if (checkTargets) {
                    known(block, "effects.expand", Set.of("from", "match", "into", "set", "quantity", "quantityInto", "quantityLine", "quantityTimes", "at"));
                    if (block.hasNonNull("at") && fields.stream().noneMatch(field -> field.name().equals(text(block, "at")) && field.type().equals("date"))) throw bad("effects.expand.at 은 이 자료의 날짜 항목입니다 (기준 정보가 그 날 유효한 것을 고른다).");
                    if (quantity.isObject()) known(quantity, "effects.expand.quantity", Set.of("into", "line", "times"));
                    Stored master = find(from), target = find(into);
                    if (master == null || master.definition().fields().isEmpty()) throw bad("effects.expand.from: 기준 정보 " + from + " 의 정의가 없습니다.");
                    if (target == null || !target.definition().fields().stream().anyMatch(field -> !field.computed())) throw bad("effects.expand.into: 만들 자료 " + into + " 의 정의가 없습니다.");
                    // a master with lines expands line by line; a master kept one pair per record (a BOM of parent-part pairs) expands record by record
                    List<Field> masterLines = master.definition().lines() != null ? master.definition().lines().fields() : master.definition().fields();
                    for (Map.Entry<String, String> entry : match.entrySet()) {
                        if (master.definition().field(entry.getKey()) == null) throw bad("effects.expand.match: " + from + " 에 " + entry.getKey() + " 항목이 없습니다. 위쪽 항목: " + names(master.definition().fields()));
                        if (fields.stream().noneMatch(field -> field.name().equals(entry.getValue()))) throw bad("effects.expand.match: 이 자료에 " + entry.getValue() + " 항목이 없습니다.");
                    }
                    if (masterLines.stream().noneMatch(field -> field.name().equals(qLine) && field.type().equals("number"))) throw bad("effects.expand.quantity.line 은 " + from + " 의 줄 숫자 항목입니다: " + masterLines.stream().filter(field -> field.type().equals("number")).map(Field::name).toList());
                    if (qTimes != null && fields.stream().noneMatch(field -> field.name().equals(qTimes) && field.type().equals("number"))) throw bad("effects.expand.quantity.times 는 이 자료의 숫자 항목입니다.");
                    if (target.definition().field(qInto) == null) throw bad("effects.expand.quantity.into: " + into + " 에 " + qInto + " 항목이 없습니다.");
                    for (Map.Entry<String, String> entry : set.entrySet()) {
                        if (target.definition().field(entry.getKey()) == null) throw bad("effects.expand.set: " + into + " 에 " + entry.getKey() + " 항목이 없습니다. 있는 항목: " + names(target.definition().fields()));
                        String value = entry.getValue();
                        if (value.equals("id") || value.equals("today")) continue;
                        if (value.startsWith("line.")) {
                            String[] path = value.substring(5).split("\\.");
                            Field first = masterLines.stream().filter(field -> field.name().equals(path[0])).findFirst().orElse(null);
                            if (first == null) throw bad("effects.expand.set: " + from + " 의 줄에 " + path[0] + " 항목이 없습니다. 줄 항목: " + names(masterLines));
                            if (path.length > 1) {
                                Stored far = first.ref() == null || !first.ref().line() ? null : find(first.ref().entity());
                                if (far == null || far.definition().lines() == null || far.definition().lines().fields().stream().noneMatch(field -> field.name().equals(path[1])))
                                    throw bad("effects.expand.set: line." + path[0] + "." + path[1] + " - " + path[0] + " 은(는) 다른 기준 정보의 줄을 가리키는 항목이어야 하고, " + path[1] + " 은(는) 그 줄의 항목이어야 합니다.");
                            }
                        } else if (fields.stream().noneMatch(field -> field.name().equals(value))) throw bad("effects.expand.set: 이 자료에 " + value + " 항목이 없습니다 (이 자료의 항목, id, today, line.<줄 항목>).");
                    }
                }
                out.add(new Effect(on, null, null, null, new Expand(from, match, into, set, qInto, qLine, qTimes, block.hasNonNull("at") ? text(block, "at") : null)));
                continue;
            }
            if (item.hasNonNull("fill")) {
                if (item.hasNonNull("create") || item.hasNonNull("act")) throw bad("effects 에는 create, act, fill 중 하나만 적습니다.");
                if (!on.equals("create")) throw bad("effects.fill 은 on 이 create(등록할 때)일 때만 씁니다.");
                String entity = text(item.get("fill"), "entity"), action = text(item.get("fill"), "action");
                if (checkTargets) {
                    known(item.get("fill"), "effects.fill", Set.of("entity", "action"));
                    Stored other = find(entity);
                    if (other == null || other.definition().status() == null || other.definition().status().actions().stream().noneMatch(candidate -> candidate.name().equals(action)))
                        throw bad("effects.fill.action 은 " + entity + " 의 status.actions name 입니다" + (other != null && other.definition().status() != null ? ": " + other.definition().status().actions().stream().map(Action::name).toList() : " (그 자료에 상태가 없습니다)") + ".");
                }
                out.add(new Effect(on, null, null, new Fill(entity, action)));
                continue;
            }
            if (item.hasNonNull("create") == item.hasNonNull("act")) throw bad("effects 에는 create(다른 자료 만들기) 와 act(가리키는 자료의 상태 바꾸기) 중 하나만 적습니다.");
            if (item.hasNonNull("create")) {
                JsonNode make = item.get("create");
                String entity = text(make, "entity");
                Map<String, String> set = new LinkedHashMap<>(), lineSet = null;
                for (Map.Entry<String, JsonNode> entry : make.path("set").properties()) set.put(entry.getKey(), entry.getValue().asString());
                if (make.hasNonNull("lines")) { lineSet = new LinkedHashMap<>(); for (Map.Entry<String, JsonNode> entry : make.get("lines").path("set").properties()) lineSet.put(entry.getKey(), entry.getValue().asString()); }
                if (set.isEmpty()) throw bad("effects.create.set 에 만들 자료의 항목을 무엇으로 채울지 적어야 합니다 ({\"<만들 자료의 항목>\": \"<이 자료의 항목 | id | today>\"}).");
                if (lineSet != null && lines == null) throw bad("effects.create.lines 는 이 자료에 줄 표가 있을 때만 씁니다.");
                for (String source : set.values()) if (!source.equals("id") && !source.equals("today") && among(fields, lines, source, false) == null) throw bad("effects.create.set: 이 자료에 " + source + " 항목이 없습니다 (id, today 도 쓸 수 있음).");
                if (lineSet != null) for (String source : lineSet.values()) if (among(fields, lines, source, true) == null) throw bad("effects.create.lines.set: 이 자료의 줄 표에 " + source + " 항목이 없습니다.");
                if (checkTargets) {
                    Stored other = entity.matches(KEY) && !entity.equals(key) ? find(entity) : null;
                    if (other == null || other.definition().summary() != null || other.definition().dashboard() != null) throw bad("effects.create.entity: 만들 자료 " + entity + " 의 정의가 없습니다. 그 등록 화면이 먼저 있어야 합니다.");
                    for (String target : set.keySet()) if (other.definition().field(target) == null) throw bad("effects.create.set: " + entity + " 에 " + target + " 항목이 없습니다. 있는 항목: " + names(other.definition().fields()));
                    if (lineSet != null) {
                        if (other.definition().lines() == null) throw bad("effects.create.lines: " + entity + " 에는 줄 표가 없습니다.");
                        for (String target : lineSet.keySet()) if (other.definition().lines().fields().stream().noneMatch(field -> field.name().equals(target))) throw bad("effects.create.lines.set: " + entity + " 의 줄 표에 " + target + " 항목이 없습니다. 있는 항목: " + names(other.definition().lines().fields()));
                    }
                    for (Field field : other.definition().fields()) if (field.required() && !set.containsKey(field.name()))
                        throw bad("effects.create.set: " + entity + " 의 필수 항목 " + field.name() + "(" + field.label() + ") 을(를) 채워야 합니다. 이 자료에 그 값이 될 항목이 없으면 이 자동 처리는 만들 수 없습니다 (먼저 그 항목을 이 자료에 추가해야 합니다).");
                    if (other.definition().lines() != null && other.definition().lines().min() > 0 && lineSet == null)
                        throw bad("effects.create: " + entity + " 은(는) 줄 표가 한 줄 이상 있어야 저장됩니다. 이 자료에 줄 표가 없으면 이 자동 처리는 만들 수 없습니다.");
                    // What is carried over must be the same kind of thing: a date into a date, a customer into a customer.
                    for (Map.Entry<String, String> entry : set.entrySet()) fits(key, other.definition().field(entry.getKey()), entry.getValue(), among(fields, lines, entry.getValue(), false), entity);
                    if (lineSet != null) for (Map.Entry<String, String> entry : lineSet.entrySet())
                        fits(key, other.definition().lines().fields().stream().filter(field -> field.name().equals(entry.getKey())).findFirst().orElse(null), entry.getValue(), among(fields, lines, entry.getValue(), true), entity);
                }
                out.add(new Effect(on, new Make(entity, set, lineSet == null ? null : new EffectLines(lineSet)), null));
            } else {
                String via = text(item.get("act"), "via"), action = text(item.get("act"), "action");
                Field pointer = among(fields, lines, via, false);
                if (pointer == null || pointer.ref() == null) throw bad("effects.act.via 는 이 자료의 ref 항목입니다 (상태를 바꿀 자료를 가리키는 항목).");
                if (checkTargets) {
                    Stored other = find(pointer.ref().entity());
                    if (other == null || other.definition().status() == null || other.definition().status().actions().stream().noneMatch(candidate -> candidate.name().equals(action)))
                        throw bad("effects.act.action 은 " + pointer.ref().entity() + " 의 status.actions name 입니다" + (other != null && other.definition().status() != null ? ": " + other.definition().status().actions().stream().map(Action::name).toList() : " (그 자료에 상태가 없습니다)") + ".");
                }
                out.add(new Effect(on, null, new Act(via, action)));
            }
        }
        return out;
    }

    private static List<String> names(List<Field> fields) { return fields.stream().map(Field::name).toList(); }
    /** A definition says only what the framework understands: an entry it does not know is refused, never silently dropped. */
    /** {"field": "<name>", "is": ["<value>", ...]} (a single value may be given bare). */
    /** A record that takes quantities out through the ledger is refused already when the place holds too little: a limit capping it by what
     *  came in (the receipts of that thing at that place) says the same thing worse (it forgets what went out before) and is left out. */
    private List<Limit> withoutStockCap(List<Limit> limits, JsonNode ledger) {
        if (ledger == null || limits.isEmpty()) return limits;
        String direction = text(ledger, "direction"), thing = text(ledger, "thing"), place = text(ledger, "place");
        if (!(direction.equals("out") || direction.equals("move")) || thing.isEmpty() || place.isEmpty()) return limits;
        List<Limit> kept = new ArrayList<>();
        for (Limit limit : limits) {
            Stored other = limit.entity().matches(KEY) ? find(limit.entity()) : null;
            Ledger theirs = other == null ? null : other.definition().ledger();
            boolean cap = theirs != null && (theirs.direction().equals("in") || theirs.direction().equals("count")) && limit.by().contains(thing) && limit.by().contains(place);
            if (!cap) kept.add(limit);
        }
        return kept;
    }

    /** from / to: two date fields (a day counts whole: 3-5 and 5-7 meet) or two time fields (half open: 10:00-11:00 and 11:00-12:00 do not). */
    public record NoOverlap(String from, String to, List<String> by, List<String> ignore, String message) {}

    private List<NoOverlap> noOverlap(JsonNode list, List<Field> fields, Status status) {
        List<NoOverlap> out = new ArrayList<>();
        if (list == null || list.isNull()) return out;
        if (list.isObject()) list = mapper.createArrayNode().add(list);
        if (!list.isArray()) throw bad("noOverlap 은 [{\"from\": \"<시작 항목>\", \"to\": \"<끝 항목>\", \"by\": [\"<같으면 겹치면 안 되는 항목>\"], \"message\": \"...\"}] 입니다.");
        for (JsonNode item : list) {
            known(item, "noOverlap", Set.of("from", "to", "by", "ignore", "message"));
            String from = named(fields, text(item, "from"), "noOverlap.from"), to = named(fields, text(item, "to"), "noOverlap.to");
            Field start = field(fields, from), end = field(fields, to);
            if (start == null || end == null || from.equals(to) || !start.type().equals(end.type()) || !(start.type().equals("date") || start.type().equals("time")))
                throw bad("noOverlap 의 from 과 to 는 같은 종류의 날짜 항목 둘이거나 시각 항목 둘입니다 (" + text(item, "from") + ", " + text(item, "to") + ").");
            if (!start.required() || !end.required()) throw bad("noOverlap 의 from 과 to 는 필수 항목이어야 합니다 (" + from + ", " + to + ").");
            List<String> by = new ArrayList<>(), ignore = new ArrayList<>();
            for (JsonNode name : item.path("by")) by.add(named(fields, name.asString(), "noOverlap.by"));
            for (JsonNode code : item.path("ignore")) ignore.add(code.asString());
            if (by.size() > 4) throw bad("noOverlap.by 에는 항목을 0~4개 적습니다.");
            if (start.type().equals("time") && by.stream().noneMatch(name -> field(fields, name).type().equals("date")))
                throw bad("noOverlap: 시각끼리 견줄 때는 그 날짜 항목을 by 에 넣습니다 (같은 날끼리만 견준다).");
            if (!ignore.isEmpty() && (status == null || !status.values().stream().map(StatusValue::code).toList().containsAll(ignore)))
                throw bad("noOverlap.ignore 는 이 자료의 상태 code 입니다 (취소된 건을 세지 않으려면): " + ignore);
            String message = text(item, "message");
            out.add(new NoOverlap(from, to, by, ignore, message.isEmpty() ? null : message));
        }
        return out;
    }
    private static Field field(List<Field> fields, String name) { return fields.stream().filter(one -> one.name().equals(name)).findFirst().orElse(null); }

    /** over.mine: the entity must have a user field (who registered the record) to tell whose a record is. */
    private boolean mineOf(JsonNode block, String entity) {
        if (!block.path("mine").asBoolean(false)) return false;
        Stored target = find(entity);
        if (target != null && target.definition().fields().stream().noneMatch(field -> field.type().equals("user")))
            throw bad("over.mine: " + entity + " 에 등록한 사람을 담는 user 항목이 없습니다. 먼저 그 자료에 {\"type\": \"user\"} 항목(예: 신청자, 예약자)을 둡니다.");
        return true;
    }
    /** The field holding who registered a record (type user), or null. */
    public static String userField(Definition definition) {
        return definition.fields().stream().filter(field -> field.type().equals("user")).map(Field::name).findFirst().orElse(null);
    }

    /** pointer: the field pointing at the earlier record; carry: fields taken over from it (same name and kind); ask: fields typed in each row. */
    public record From(String entity, String pointer, List<String> statuses, List<String> carry, List<String> ask) {}

    private static String fromEntity(JsonNode block) { return block.isTextual() ? block.asString().trim() : text(block, "entity"); }
    private static String camelKey(String key) {
        StringBuilder out = new StringBuilder();
        for (String part : key.split("_")) if (!part.isEmpty()) out.append(out.length() == 0 ? part : part.substring(0, 1).toUpperCase() + part.substring(1));
        return out.toString();
    }

    /** "from": {"entity": <earlier key>, "statuses": [...]} - the records of this entity are made from the earlier one's, one each: the pointer,
     *  the limit (each earlier record once) and follows are put in here when they are not written, so the rest of the definition is read as usual. */
    private JsonNode withFrom(String key, JsonNode node, boolean checkTargets) {
        JsonNode block = node.get("from");
        if (block.isObject()) known(block, "from", Set.of("entity", "statuses", "pointer", "carry", "ask"));     // (the last three: read back as stored, worked out again)
        String entity = fromEntity(block);
        Stored earlier = entity.matches(KEY) && !entity.equals(key) ? find(entity) : null;
        if (earlier == null || earlier.definition().fields().isEmpty()) {
            if (checkTargets) throw bad("from.entity: 이어 만들 앞 자료 " + entity + " 의 정의가 없습니다 (자료를 담는 화면의 key).");
            return node;
        }
        tools.jackson.databind.node.ObjectNode out = (tools.jackson.databind.node.ObjectNode) node;
        tools.jackson.databind.node.ArrayNode fields = out.withArray("fields");
        String pointer = null;
        for (JsonNode field : fields) if (field.path("ref").path("entity").asString("").equals(entity)) { pointer = text(field, "name"); break; }
        String noun = earlier.definition().title().replaceAll("\\s*(등록|관리|입력)$", "");
        if (pointer == null) {
            pointer = camelKey(entity) + "Id";
            Field shown = earlier.definition().fields().stream().filter(field -> field.type().equals("text")).findFirst()
                    .orElse(earlier.definition().fields().stream().filter(field -> field.type().equals("serial")).findFirst().orElse(earlier.definition().fields().get(0)));
            tools.jackson.databind.node.ObjectNode field = fields.insertObject(0);
            field.put("name", pointer).put("label", noun).put("type", "ref");
            field.putObject("ref").put("entity", entity).put("label", shown.name());
        }
        if (!out.hasNonNull("follows")) out.put("follows", pointer);
        boolean limited = false;
        for (JsonNode limit : out.path("limits")) if (text(limit, "entity").equals(entity)) limited = true;
        if (!limited) {
            tools.jackson.databind.node.ObjectNode limit = out.withArray("limits").addObject();
            limit.putArray("by").add(pointer);
            limit.put("entity", entity);
            limit.putArray("entityBy").add("id");
            limit.put("message", "이미 이어진 " + noun + "입니다.");
        }
        return out;
    }

    /** What the screen takes over from the earlier list: same-named fields of the same kind carried, the rest typed in each row. */
    private From from(String key, JsonNode node, List<Field> fields, boolean checkTargets) {
        if (!node.hasNonNull("from")) return null;
        String entity = fromEntity(node.get("from"));
        Stored earlier = find(entity);
        if (earlier == null) return null;
        String pointer = fields.stream().filter(field -> field.ref() != null && field.ref().entity().equals(entity)).map(Field::name).findFirst().orElse(null);
        List<String> statuses = new ArrayList<>();
        for (JsonNode code : node.get("from").path("statuses")) statuses.add(code.asString());
        if (!statuses.isEmpty() && (earlier.definition().status() == null || !earlier.definition().status().values().stream().map(StatusValue::code).toList().containsAll(statuses)))
            throw bad("from.statuses 는 " + entity + " 의 상태 code 입니다: " + statuses);
        List<String> carry = new ArrayList<>(), ask = new ArrayList<>();
        for (Field field : fields) {
            if (field.computed() || field.name().equals(pointer)) continue;
            Field theirs = earlier.definition().field(field.name());
            if (theirs != null && theirs.type().equals(field.type()) && (field.ref() == null || (theirs.ref() != null && theirs.ref().entity().equals(field.ref().entity())))) carry.add(field.name());
            else if (List.of("text", "number", "date", "time", "yesno", "ref").contains(field.type())) ask.add(field.name());
        }
        return new From(entity, pointer, statuses, carry, ask);
    }
    /** The take-over a from-screen offers (its own screen lists the earlier records still open). */
    public static Take takeOf(Definition definition) {
        From from = definition.from();
        if (from == null) return null;
        Map<String, String> set = new LinkedHashMap<>();
        for (String name : from.carry()) set.put(name, name);
        return new Take(definition.key(), from.entity(), from.statuses(), set, Map.of(), List.of(), null, from.ask());
    }

    /** A screen always finds its records by its automatic number and its first date (a period); when no field is marked search at all,
     *  the fields choosing other records are search fields too (two at most; the earlier record of a from-screen first). */
    private static List<Field> withKeySearch(List<Field> fields, JsonNode node) {
        if (fields.isEmpty()) return fields;
        boolean marked = fields.stream().anyMatch(Field::search);
        String pointer = node.path("follows").asString("");
        java.util.Set<String> keys = new java.util.LinkedHashSet<>();
        // always: the automatic number (the record's key) and the first date (a period)
        fields.stream().filter(field -> field.type().equals("serial")).forEach(field -> keys.add(field.name()));
        fields.stream().filter(field -> field.type().equals("date")).findFirst().ifPresent(field -> keys.add(field.name()));
        if (!marked) {           // nothing chosen: the fields choosing other records too (the earlier record of a from-screen first)
            fields.stream().filter(field -> field.name().equals(pointer)).forEach(field -> keys.add(field.name()));
            fields.stream().filter(field -> field.ref() != null && !field.name().equals(pointer)).limit(keys.contains(pointer) ? 1 : 2).forEach(field -> keys.add(field.name()));
            if (keys.isEmpty()) fields.stream().filter(field -> field.required() && field.type().equals("text")).findFirst().ifPresent(field -> keys.add(field.name()));
        }
        List<Field> out = new ArrayList<>();
        for (Field f : fields)
            out.add(keys.contains(f.name()) && !f.search() ? new Field(f.name(), f.label(), f.type(), f.required(), true, f.codeGroup(), f.ref(), f.prefix(), f.formula(), f.sum(), f.fill(), f.min(), f.max(),
                    f.unique(), f.pick(), f.decimals(), f.showWhen(), f.requiredWhen(), f.lockWhen()) : f);
        return out;
    }

    /** complete_ship, complete-ship -> completeShip: an action name written the other usual ways is read as meant. */
    private static String camel(String name) {
        if (!name.matches("[A-Za-z][A-Za-z0-9]*([_-][A-Za-z0-9]+)+")) return name;
        StringBuilder out = new StringBuilder();
        for (String part : name.split("[_-]")) out.append(out.length() == 0 ? part.substring(0, 1).toLowerCase() + part.substring(1) : part.substring(0, 1).toUpperCase() + part.substring(1));
        return out.toString();
    }

    private Condition condition(JsonNode item, String part, String name) {
        if (!item.hasNonNull(part)) return null;
        JsonNode block = item.get(part);
        boolean not = block.isObject() && (block.has("isNot") || block.path("not").asBoolean(false));
        String key = block.isObject() && block.has("isNot") ? "isNot" : "is";
        if (!block.isObject() || text(block, "field").isEmpty() || !block.has(key)) throw bad("항목 " + name + " 의 " + part + " 는 {\"field\": \"<보는 항목 name>\", \"is\": [\"<값>\", ...]} 모양입니다.");
        List<String> is = new ArrayList<>();
        for (JsonNode value : block.get(key).isArray() ? block.get(key) : mapper.createArrayNode().add(block.get(key)))
            is.add(value.isBoolean() ? String.valueOf(value.asBoolean()) : value.isNull() ? "" : value.asString().trim());
        if (is.isEmpty() || is.size() > 30) throw bad("항목 " + name + " 의 " + part + ".is 에 값을 1~30개 적습니다.");
        return new Condition(text(block, "field"), is, not);
    }

    private static void known(JsonNode node, String where, Set<String> allowed) {
        if (node == null || !node.isObject()) return;
        for (Map.Entry<String, JsonNode> entry : node.properties())
            if (!allowed.contains(entry.getKey()) && !entry.getValue().isNull())
                throw bad(where + " 에 '" + entry.getKey() + "' 은(는) 쓸 수 없습니다. 쓸 수 있는 것: " + new java.util.TreeSet<>(allowed)
                        + ". 프레임워크에 없는 기능은 정의에 적어도 동작하지 않으므로, 요청이 그 기능 없이는 안 되면 정의로 할 수 없는 요청입니다.");
    }

    private static String text(JsonNode node, String name) { return node != null && node.hasNonNull(name) ? node.get(name).asString().trim() : ""; }
    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
}
