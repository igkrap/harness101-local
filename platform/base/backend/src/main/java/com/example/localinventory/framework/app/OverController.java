package com.example.localinventory.framework.app;

import com.example.localinventory.framework.system.SystemAccessService;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;

/**
 * A work screen's side of an entity: the same records and rules as the entity's own API, narrowed to the statuses and
 * actions the work screen is for. Nothing is deleted here; new records only on a screen made for registering (create) - a
 * 등록 screen beside the entity's own 관리 screen. The path (/api/over/{key}) belongs to the work screen's program, so who may
 * register, approve or hand over is decided by who is given that screen.
 */
@RestController
@RequestMapping("/api/over/{key}")
public class OverController {
    private final AppDefinitions definitions;
    private final RecordController records;
    private final SystemAccessService access;
    public OverController(AppDefinitions definitions, RecordController records, SystemAccessService access) {
        this.definitions = definitions; this.records = records; this.access = access;
    }

    private AppDefinitions.Over over(String key, Authentication authentication) {
        AppDefinitions.Stored stored = definitions.find(key);
        boolean admin = access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
        if (stored == null || stored.definition().over() == null || (!stored.status().equals("PUBLISHED") && !admin))
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "화면을 찾지 못했습니다: " + key);
        return stored.definition().over();
    }
    private static boolean shown(AppDefinitions.Over over, Map<String, Object> row) {
        return over.statuses().isEmpty() || over.statuses().contains((String) row.get("status"));
    }

    @GetMapping
    public List<Map<String, Object>> list(@PathVariable String key, @RequestParam Map<String, String> filters, Authentication authentication,
                                          jakarta.servlet.http.HttpServletResponse response) {
        AppDefinitions.Over over = over(key, authentication);
        // The statuses narrow the list in the database, so a long history of finished records does not push the waiting ones out of the page.
        AppDefinitions.Definition entity = definitions.find(over.entity()).definition();
        if (over.mine()) {           // only the signed-in person's own records: whatever the query asked for that field
            filters = new java.util.LinkedHashMap<>(filters);
            filters.put(AppDefinitions.userField(entity), authentication.getName());
        }
        RecordController.Page page = records.page(entity, filters, over.statuses());
        response.setHeader("X-Total-Count", String.valueOf(page.total()));
        return page.rows();
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String key, @PathVariable long id, Authentication authentication) {
        AppDefinitions.Over over = over(key, authentication);
        Map<String, Object> row = records.get(over.entity(), id, authentication);
        if (!shown(over, row)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "이 화면에서 다루는 상태의 자료가 아닙니다.");
        if (over.mine() && !authentication.getName().equals(row.get(AppDefinitions.userField(definitions.find(over.entity()).definition()))))
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "본인이 등록한 자료만 이 화면에서 다룹니다.");
        return row;
    }

    @GetMapping("/{id}/files")
    public List<Map<String, Object>> files(@PathVariable String key, @PathVariable long id, Authentication authentication) {
        get(key, id, authentication);
        return records.files(over(key, authentication).entity(), id, authentication);
    }

    @GetMapping("/{id}/files/{file}")
    public org.springframework.http.ResponseEntity<byte[]> file(@PathVariable String key, @PathVariable long id, @PathVariable long file, Authentication authentication) {
        get(key, id, authentication);
        return records.file(over(key, authentication).entity(), id, file, authentication);
    }

    @GetMapping("/{id}/history")
    public List<Map<String, Object>> history(@PathVariable String key, @PathVariable long id, Authentication authentication) {
        get(key, id, authentication);
        return records.history(over(key, authentication).entity(), id, authentication);
    }

    @PostMapping("/_lookup")
    public Map<String, Object> lookup(@PathVariable String key, @RequestBody JsonNode body, Authentication authentication) {
        AppDefinitions.Over over = over(key, authentication);
        return records.lookedUp(definitions.find(over.entity()).definition(), body);
    }

    @PostMapping
    public Map<String, Object> create(@PathVariable String key, @RequestBody JsonNode body, Authentication authentication) {
        AppDefinitions.Over over = over(key, authentication);
        if (!over.create()) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "이 화면에서는 새로 등록할 수 없습니다.");
        return records.createFrom(over.entity(), body, authentication, true);
    }

    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable String key, @PathVariable long id, @RequestBody JsonNode body, Authentication authentication) {
        AppDefinitions.Over over = over(key, authentication);
        if (!over.edit()) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "이 화면에서는 내용을 고칠 수 없습니다.");
        get(key, id, authentication);
        return records.update(over.entity(), id, body, authentication);
    }

    /** body (optional): {"values": {...}} - the fields this screen asks with the action (over.ask), written with it and nothing else. */
    @PostMapping("/{id}/actions/{action}")
    @org.springframework.transaction.annotation.Transactional
    public Map<String, Object> act(@PathVariable String key, @PathVariable long id, @PathVariable String action,
                                   @RequestParam(defaultValue = "false") boolean check, @RequestBody(required = false) JsonNode body, Authentication authentication) {
        AppDefinitions.Over over = over(key, authentication);
        if (!over.actions().contains(action)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "이 화면에서 하는 동작이 아닙니다: " + action);
        Map<String, Object> row = get(key, id, authentication);
        List<String> asked = over.asked(action);
        if (!asked.isEmpty() && !check) {
            AppDefinitions.Definition entity = definitions.find(over.entity()).definition();
            JsonNode values = body == null ? null : body.path("values");
            tools.jackson.databind.node.ObjectNode changed = new tools.jackson.databind.json.JsonMapper().valueToTree(row);
            for (String name : asked) {
                JsonNode value = values == null ? null : values.get(name);
                if (value == null || value.isNull() || value.asString("").isBlank())
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, entity.field(name).label() + "을(를) 적어야 " + entity.status().actions().stream()
                            .filter(one -> one.name().equals(action)).map(AppDefinitions.Action::label).findFirst().orElse(action) + "할 수 있습니다.");
                changed.set(name, value);
            }
            records.update(over.entity(), id, changed, authentication);            // only the asked fields differ from what is there
            return records.perform(over.entity(), id, action, false, authentication, true, true);
        }
        return records.perform(over.entity(), id, action, check, authentication, true);
    }
}
