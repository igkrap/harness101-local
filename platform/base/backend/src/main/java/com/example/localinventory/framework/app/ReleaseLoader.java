package com.example.localinventory.framework.app;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * An operating copy takes its screens from a setup pack: a folder (release/) holding the screen definitions, the common
 * codes and the menu arrangement as files. When the server starts and that folder is there, what it holds is applied -
 * once per content, all or nothing. So installing is "start the server with the pack beside it", and updating is
 * "put the newer pack there and start again". The copy's own records, users, roles and permissions are never touched.
 *
 * Where screens are made (development) there is no such folder and nothing happens.
 */
@Component
public class ReleaseLoader {
    private static final Logger log = LoggerFactory.getLogger(ReleaseLoader.class);
    /** Parts of a definition that may name a screen which comes later in the pack: they go in with a second pass. */
    private static final Set<String> CARRIED = Set.of("rules", "effects", "limits");
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final Path folder;
    private final ObjectMapper mapper = tools.jackson.databind.json.JsonMapper.builder().build();

    private final RecordStore store;
    public ReleaseLoader(AppDefinitions definitions, JdbcTemplate jdbc, TransactionTemplate transaction, RecordStore store, @Value("${APP_RELEASE_DIR:/app/release}") String folder) {
        this.definitions = definitions; this.jdbc = jdbc; this.transaction = transaction; this.store = store; this.folder = Path.of(folder);
    }

    @EventListener(ApplicationReadyEvent.class)
    public void load() {
        // First of all, every screen's own tables are there and up to its definition (and records an older version kept in one table are carried into them).
        try { store.prepare(); } catch (RuntimeException failed) { log.error("screen tables could not be prepared: {}", failed.getMessage()); }
        if (!Files.isDirectory(folder.resolve("definitions"))) return;
        String mark;
        try { mark = mark(); } catch (Exception error) { note("error", "배포 묶음을 읽지 못했습니다: " + error.getMessage()); return; }
        if (mark.equals(setting("release_applied"))) return;
        try {
            String summary = transaction.execute(this::apply);
            set("release_applied", mark);
            set("release_applied_at", java.time.Instant.now().toString());
            note("ok", summary);
            log.info("Setup pack applied: {}", summary);
        } catch (Exception error) {      // nothing of the pack was kept; the copy runs on as it was
            String reason = error instanceof org.springframework.web.server.ResponseStatusException refused ? refused.getReason() : error.getMessage();
            note("error", reason);
            log.error("Setup pack refused, nothing applied: {}", reason);
        }
    }

    private String apply(org.springframework.transaction.TransactionStatus status) {
        boolean first = setting("release_applied") == null;
        JsonNode codes = read("codes.json"), menus = read("menus.json"), settings = read("settings.json");
        if (first && settings != null)       // a new copy starts out looking like the place it was made in; from then on its settings are its own
            for (JsonNode row : settings) set(row.path("setting_key").asString(), row.path("setting_value").asString());
        if (codes != null) {
            for (JsonNode group : codes.path("groups"))
                jdbc.update("INSERT INTO sys_code_groups (group_code, group_name, description, enabled) VALUES (?, ?, ?, ?) "
                        + "ON CONFLICT (group_code) DO UPDATE SET group_name = EXCLUDED.group_name, description = EXCLUDED.description, enabled = EXCLUDED.enabled",
                        group.path("group_code").asString(), group.path("group_name").asString(), group.path("description").asString(""), group.path("enabled").asBoolean(true));
            for (JsonNode code : codes.path("codes"))
                jdbc.update("INSERT INTO sys_codes (group_code, code, code_name, sort_order, enabled) VALUES (?, ?, ?, ?, ?) "
                        + "ON CONFLICT (group_code, code) DO UPDATE SET code_name = EXCLUDED.code_name, sort_order = EXCLUDED.sort_order, enabled = EXCLUDED.enabled",
                        code.path("group_code").asString(), code.path("code").asString(), code.path("code_name").asString(), code.path("sort_order").asInt(0), code.path("enabled").asBoolean(true));
        }
        int[] counts = screens();
        if (menus != null) menus(menus);
        return "새 화면 " + counts[0] + "개, 바뀐 화면 " + counts[1] + "개, 그대로 " + counts[2] + "개";
    }

    /** New and changed definitions. Returns {new, changed, same}. */
    private int[] screens() {
        Map<String, JsonNode> pack = new LinkedHashMap<>();
        try (Stream<Path> files = Files.list(folder.resolve("definitions"))) {
            for (Path file : files.filter(path -> path.getFileName().toString().endsWith(".json")).sorted().toList()) {
                JsonNode row = mapper.readTree(Files.readString(file, StandardCharsets.UTF_8));
                pack.put(row.path("key").asString(), row);
            }
        } catch (java.io.IOException error) { throw new IllegalStateException(error.getMessage(), error); }
        Map<String, String> marks = new HashMap<>();
        jdbc.query("SELECT setting_key, setting_value FROM sys_settings WHERE setting_key LIKE 'release_screen:%'", row -> { marks.put(row.getString(1).substring(15), row.getString(2)); });
        int made = 0, changed = 0, same = 0;
        Map<String, JsonNode> waiting = new LinkedHashMap<>();
        for (Map.Entry<String, JsonNode> entry : pack.entrySet()) {
            String mark = hex(entry.getValue().path("definition").toString());
            if (definitions.find(entry.getKey()) != null && mark.equals(marks.get(entry.getKey()))) { same++; continue; }
            if (definitions.find(entry.getKey()) == null) made++; else changed++;
            waiting.put(entry.getKey(), entry.getValue());
        }
        // First without the parts that may name a later screen, again and again while any is still accepted; then whole.
        Map<String, JsonNode> todo = new LinkedHashMap<>(waiting);
        String problem = null;
        while (!todo.isEmpty()) {
            List<String> done = new ArrayList<>();
            for (Map.Entry<String, JsonNode> entry : todo.entrySet()) {
                ObjectNode bare = ((ObjectNode) entry.getValue().path("definition")).deepCopy();
                CARRIED.forEach(bare::remove);
                // Judged first (reading only): a definition that names a screen not yet there is refused before anything is written, and waits for the next round.
                try { definitions.parse(entry.getKey(), bare, true); }
                catch (RuntimeException refused) {
                    problem = title(entry.getValue()) + ": " + (refused instanceof org.springframework.web.server.ResponseStatusException answer ? answer.getReason() : refused.getMessage());
                    continue;
                }
                save(entry.getKey(), bare, entry.getValue().path("programCode").asString());
                done.add(entry.getKey());
            }
            if (done.isEmpty()) throw new IllegalStateException(problem);
            done.forEach(todo::remove);
        }
        for (Map.Entry<String, JsonNode> entry : waiting.entrySet()) {
            JsonNode definition = entry.getValue().path("definition");
            if (CARRIED.stream().anyMatch(part -> definition.hasNonNull(part) && !definition.path(part).isEmpty())) {
                try { save(entry.getKey(), definition, entry.getValue().path("programCode").asString()); }
                catch (org.springframework.web.server.ResponseStatusException refused) { throw new IllegalStateException(title(entry.getValue()) + ": " + refused.getReason()); }
            }
            set("release_screen:" + entry.getKey(), hex(definition.toString()));
        }
        return new int[] { made, changed, same };
    }

    private static String title(JsonNode row) { return row.path("definition").path("title").asString(row.path("key").asString()); }

    /** The same as publishing through the administrator's API, keeping the program code the screen was made with. */
    private void save(String key, JsonNode node, String programCode) {
        AppDefinitions.Definition definition = definitions.parse(key, node, true);
        AppDefinitions.Stored current = definitions.find(key);
        String json = definitions.json(definition), program = current == null ? programCode : current.programCode();
        if (current == null) jdbc.update("INSERT INTO app_definitions (entity_key, program_code, status, definition, created_by) VALUES (?, ?, 'PUBLISHED', ?, 'release')", key, program, json);
        else jdbc.update("UPDATE app_definitions SET definition = ?, status = 'PUBLISHED', revision = revision + 1, updated_by = 'release', updated_at = CURRENT_TIMESTAMP WHERE entity_key = ?", json, key);
        String keywords = String.join(",", definition.keywords());
        String path = definition.ledgerView() != null ? "/api/ledger/" : definition.dashboard() != null
                ? String.join(",", definition.dashboard().panels().stream().map(panel -> "/api/summary/" + panel.summary()).distinct().toList())
                : (definition.over() != null ? "/api/over/" : definition.take() != null ? "/api/take/" :  definition.calendar() != null ? "/api/calendar/" : definition.tree() != null ? "/api/tree/" : definition.summary() != null ? "/api/summary/" : "/api/data/") + key;
        if (definition.dataOnly()) jdbc.update("DELETE FROM sys_programs WHERE program_code = ?", program);          // data only: no program, no menu
        else if (jdbc.update("UPDATE sys_programs SET program_name = ?, api_paths = ?, keywords = ? WHERE program_code = ?", definition.title(), path, keywords, program) == 0)
            jdbc.update("INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES (?, ?, ?, FALSE, ?)", program, definition.title(), path, keywords);
        definitions.ensureCodes(definition);
        store.ensure(definition);
    }

    /** The menu tree becomes the pack's: a program's menu keeps its row (permissions given on it stay), folders are matched by their place, what the pack no longer has goes. */
    private void menus(JsonNode menus) {
        for (JsonNode module : menus.path("modules"))
            jdbc.update("INSERT INTO sys_modules (module_code, system_code, module_name, icon, sort_order, enabled) VALUES (?, ?, ?, ?, ?, ?) "
                    + "ON CONFLICT (module_code) DO UPDATE SET module_name = EXCLUDED.module_name, icon = EXCLUDED.icon, sort_order = EXCLUDED.sort_order, enabled = EXCLUDED.enabled",
                    module.path("module_code").asString(), module.path("system_code").asString(), module.path("module_name").asString(), text(module.get("icon")), module.path("sort_order").asInt(0), module.path("enabled").asBoolean(true));
        if (menus.path("modules").isEmpty()) return;
        List<Map<String, Object>> current = jdbc.queryForList("SELECT menu_id, module_code, program_code, menu_name, parent_id, menu_type FROM sys_menus");
        Map<Long, Map<String, Object>> byId = new HashMap<>();
        for (Map<String, Object> row : current) byId.put(((Number) row.get("menu_id")).longValue(), row);
        Map<String, Long> folders = new HashMap<>(), programs = new HashMap<>();
        for (Map<String, Object> row : current) {
            long id = ((Number) row.get("menu_id")).longValue();
            if ("FOLDER".equals(row.get("menu_type"))) {
                List<String> names = new ArrayList<>();
                for (Map<String, Object> at = row; at != null; at = at.get("parent_id") == null ? null : byId.get(((Number) at.get("parent_id")).longValue())) names.add(0, (String) at.get("menu_name"));
                folders.put(row.get("module_code") + "\u0000" + String.join("\u0000", names), id);
            } else programs.put((String) row.get("program_code"), id);
        }
        Set<Long> kept = new java.util.HashSet<>();
        for (JsonNode item : menus.path("menus")) {        // sorted by depth in the pack: folders come before what they hold
            List<String> path = new ArrayList<>();
            for (JsonNode name : item.path("folders")) path.add(name.asString());
            String module = item.path("module").asString(), name = item.path("name").asString();
            Long parent = path.isEmpty() ? null : folders.get(module + "\u0000" + String.join("\u0000", path));
            if (!path.isEmpty() && parent == null) continue;
            int sort = item.path("sort").asInt(0);
            boolean enabled = item.path("enabled").asBoolean(true);
            String icon = text(item.get("icon"));
            if (item.path("type").asString().equals("FOLDER")) {
                List<String> own = new ArrayList<>(path); own.add(name);
                String place = module + "\u0000" + String.join("\u0000", own);
                Long id = folders.get(place);
                if (id == null) { id = jdbc.queryForObject("INSERT INTO sys_menus (module_code, parent_id, menu_name, sort_order, enabled, icon, menu_type) VALUES (?, ?, ?, ?, ?, ?, 'FOLDER') RETURNING menu_id", Long.class, module, parent, name, sort, enabled, icon); folders.put(place, id); }
                else jdbc.update("UPDATE sys_menus SET module_code = ?, parent_id = ?, menu_name = ?, sort_order = ?, enabled = ?, icon = ? WHERE menu_id = ?", module, parent, name, sort, enabled, icon, id);
                kept.add(id);
            } else {
                String program = item.path("program").asString();
                if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_programs WHERE program_code = ?", Integer.class, program) == 0) continue;   // a screen this copy does not have has no menu here
                Long id = programs.get(program);
                if (id == null) { id = jdbc.queryForObject("INSERT INTO sys_menus (module_code, parent_id, program_code, menu_name, sort_order, enabled, icon, menu_type) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROGRAM') RETURNING menu_id", Long.class, module, parent, program, name, sort, enabled, icon); programs.put(program, id); }
                else jdbc.update("UPDATE sys_menus SET module_code = ?, parent_id = ?, menu_name = ?, sort_order = ?, enabled = ?, icon = ? WHERE menu_id = ?", module, parent, name, sort, enabled, icon, id);
                kept.add(id);
            }
        }
        for (Long id : byId.keySet()) if (!kept.contains(id)) jdbc.update("DELETE FROM sys_menus WHERE menu_id = ?", id);
    }

    private static String text(JsonNode node) { return node == null || node.isNull() ? null : node.asString(); }

    private JsonNode read(String name) {
        Path file = folder.resolve(name);
        try { return Files.isRegularFile(file) ? mapper.readTree(Files.readString(file, StandardCharsets.UTF_8)) : null; }
        catch (java.io.IOException error) { throw new IllegalStateException(name + ": " + error.getMessage(), error); }
    }

    /** One mark for the whole folder: the same content is applied only once. */
    private String mark() throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (Stream<Path> files = Files.walk(folder)) {
            for (Path file : files.filter(path -> Files.isRegularFile(path) && path.getFileName().toString().endsWith(".json")).sorted().toList()) {
                digest.update(folder.relativize(file).toString().getBytes(StandardCharsets.UTF_8));
                digest.update(Files.readAllBytes(file));
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private static String hex(String text) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    private String setting(String key) {
        List<String> rows = jdbc.queryForList("SELECT setting_value FROM sys_settings WHERE setting_key = ?", String.class, key);
        return rows.isEmpty() ? null : rows.get(0);
    }
    private void set(String key, String value) {
        jdbc.update("INSERT INTO sys_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value", key, value == null ? "" : value);
    }
    private void note(String status, String detail) {
        set("release_status", status);
        set("release_detail", detail == null ? "" : detail.length() > 1500 ? detail.substring(0, 1500) : detail);
    }
}
