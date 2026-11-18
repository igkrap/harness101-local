package com.example.localinventory.framework.app;

import com.example.localinventory.framework.system.SystemAccessService;
import tools.jackson.databind.JsonNode;
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
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** Reading definitions (the app draws its screens from them) and, for administrators, writing them. */
@RestController
public class DefinitionController {
    private final AppDefinitions definitions;
    private final JdbcTemplate jdbc;
    private final SystemAccessService access;
    private final RecordStore store;
    private final QuantityLedger quantities;
    public DefinitionController(AppDefinitions definitions, JdbcTemplate jdbc, SystemAccessService access, RecordStore store, QuantityLedger quantities) {
        this.definitions = definitions; this.jdbc = jdbc; this.access = access; this.store = store; this.quantities = quantities;
    }

    @GetMapping("/api/meta/capabilities")
    public Map<String, Object> capabilities() { return definitions.capabilities(); }

    /** Published definitions; administrators may ask for drafts too (drafts=true). */
    @GetMapping("/api/meta/definitions")
    public List<Map<String, Object>> list(@RequestParam(defaultValue = "false") boolean drafts, Authentication authentication) {
        boolean admin = admin(authentication);
        List<Map<String, Object>> out = new ArrayList<>();
        for (AppDefinitions.Stored stored : definitions.all())
            if (stored.status().equals("PUBLISHED") || (drafts && admin)) out.add(view(stored));
        return out;
    }

    /** programCode: for a new definition, the program code to give it (a release keeps the codes of the place it was made in, so menus and permissions line up). */
    public record SaveRequest(JsonNode definition, String status, String programCode) {}

    /** Create or change a definition. status: DRAFT (default for a new one) or PUBLISHED. */
    @PutMapping("/api/system/definitions/{key}")
    @Transactional
    public Map<String, Object> save(@PathVariable String key, @RequestBody SaveRequest request, @RequestParam(defaultValue = "false") boolean validate, Authentication authentication) {
        AppDefinitions.Definition definition = definitions.parse(key, request.definition(), true);
        // validate=true: judge the definition as it would be saved under this key (rules and effects included) and store nothing.
        if (validate) { Map<String, Object> out = new LinkedHashMap<>(); out.put("key", key); out.put("valid", true); out.put("definition", definition); return out; }
        AppDefinitions.Stored current = definitions.find(key);
        String status = request.status() == null ? (current == null ? "DRAFT" : current.status()) : request.status();
        if (!status.equals("DRAFT") && !status.equals("PUBLISHED")) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "status 는 DRAFT 또는 PUBLISHED 입니다.");
        String json = definitions.json(definition);
        String program;
        if (current == null) {
            Integer last = jdbc.queryForObject("SELECT COALESCE(MAX(CAST(SUBSTRING(program_code FROM 4) AS INT)), 0) FROM app_definitions WHERE program_code ~ '^APP[0-9]{4}$'", Integer.class);
            program = String.format("APP%04d", (last == null ? 0 : last) + 1);
            if (request.programCode() != null && !request.programCode().isBlank()) {
                if (!request.programCode().matches("APP[0-9]{4}")) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "programCode 는 APP0001 같은 모양입니다.");
                if (jdbc.queryForObject("SELECT COUNT(*) FROM app_definitions WHERE program_code = ?", Integer.class, request.programCode()) > 0)
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "프로그램 코드 " + request.programCode() + " 은(는) 다른 화면이 쓰고 있습니다.");
                program = request.programCode();
            }
            jdbc.update("INSERT INTO app_definitions (entity_key, program_code, status, definition, created_by) VALUES (?, ?, ?, ?, ?)", key, program, status, json, authentication.getName());
        } else {
            program = current.programCode();
            jdbc.update("UPDATE app_definitions SET definition = ?, status = ?, revision = revision + 1, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE entity_key = ?",
                    json, status, authentication.getName(), key);
        }
        if (status.equals("PUBLISHED") && definition.dataOnly()) {
            // data only: no program of its own (and so no menu); one it had goes, with its menus and permissions
            jdbc.update("DELETE FROM sys_programs WHERE program_code = ?", program);
        } else if (status.equals("PUBLISHED")) {
            // A published definition is a program like any screen: it can be placed in menus and given permissions.
            String keywords = String.join(",", definition.keywords());
            // A dashboard reads the summaries its panels point at, so its program owns those paths (as well as each summary's own program).
            String path = definition.ledgerView() != null ? "/api/ledger/" : definition.dashboard() != null
                    ? String.join(",", definition.dashboard().panels().stream().map(panel -> "/api/summary/" + panel.summary()).distinct().toList())
                    : (definition.over() != null ? "/api/over/" : definition.take() != null ? "/api/take/" :  definition.calendar() != null ? "/api/calendar/" : definition.tree() != null ? "/api/tree/" : definition.summary() != null ? "/api/summary/" : "/api/data/") + key;
            int updated = jdbc.update("UPDATE sys_programs SET program_name = ?, api_paths = ?, keywords = ? WHERE program_code = ?", definition.title(), path, keywords, program);
            if (updated == 0) jdbc.update("INSERT INTO sys_programs (program_code, program_name, api_paths, system_program, keywords) VALUES (?, ?, ?, FALSE, ?)",
                    program, definition.title(), path, keywords);
        }
        definitions.ensureCodes(definition);      // the code groups it declares, made when missing
        store.ensure(definition);       // the screen's own tables follow its definition (made, or given the columns it lacks)
        return view(definitions.find(key));
    }

    /** Remove a definition. Refused while it has records unless force=true (then they go too). */
    @DeleteMapping("/api/system/definitions/{key}")
    @Transactional
    public Map<String, Object> delete(@PathVariable String key, @RequestParam(defaultValue = "false") boolean force) {
        AppDefinitions.Stored current = definitions.find(key);
        if (current == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "정의를 찾지 못했습니다.");
        Long records = store.count(key);
        if (records != null && records > 0 && !force) throw new ResponseStatusException(HttpStatus.CONFLICT, "자료가 " + records + "건 있어 지울 수 없습니다.");
        for (AppDefinitions.Stored other : definitions.all())
            if (!other.definition().key().equals(key) && (other.definition().fields().stream().anyMatch(field -> field.ref() != null && field.ref().entity().equals(key))
                    || (other.definition().summary() != null && (other.definition().summary().entity().equals(key)
                        || (other.definition().summary().compare() != null && key.equals(other.definition().summary().compare().entity()))))
                    || (other.definition().over() != null && other.definition().over().entity().equals(key))
                    || (other.definition().calendar() != null && other.definition().calendar().entity().equals(key))
                    || (other.definition().take() != null && (other.definition().take().entity().equals(key) || other.definition().take().from().equals(key)))
                    || (other.definition().tree() != null && other.definition().tree().entity().equals(key))
                    || (other.definition().dashboard() != null && other.definition().dashboard().panels().stream().anyMatch(panel -> panel.summary().equals(key)))))
                throw new ResponseStatusException(HttpStatus.CONFLICT, other.definition().title() + " 이(가) 이 자료를 가리키고 있어 지울 수 없습니다.");
        quantities.screenOpen(key, current.definition().title());
        store.drop(key);
        jdbc.update("DELETE FROM ledger_moves WHERE entity_key = ?", key);
        jdbc.update("DELETE FROM ledger_lots l WHERE l.source_entity = ? AND NOT EXISTS (SELECT 1 FROM ledger_moves m WHERE m.lot_id = l.lot_id)", key);
        jdbc.update("DELETE FROM app_record_files WHERE entity_key = ?", key);      // the screen itself is gone; its key may be used again
        jdbc.update("DELETE FROM app_definitions WHERE entity_key = ?", key);
        jdbc.update("DELETE FROM sys_programs p WHERE p.program_code = ? AND NOT EXISTS (SELECT 1 FROM sys_menus m WHERE m.program_code = p.program_code)", current.programCode());
        return Map.of("deleted", true);
    }

    private Map<String, Object> view(AppDefinitions.Stored stored) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("key", stored.definition().key());
        out.put("programCode", stored.programCode());
        out.put("status", stored.status());
        out.put("revision", stored.revision());
        out.put("definition", stored.definition());
        return out;
    }

    private boolean admin(Authentication authentication) {
        return access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
    }
}
