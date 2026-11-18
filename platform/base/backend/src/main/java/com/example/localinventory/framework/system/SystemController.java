package com.example.localinventory.framework.system;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Administration of the common system framework (administrators only; see WorkspaceSecurity). */
@RestController
@RequestMapping("/api/system")
public class SystemController {
    private final SystemAccessService access;
    public SystemController(SystemAccessService access) { this.access = access; }

    public record SyncRequest(List<SystemAccessService.ProgramInput> programs) {}

    /** The app reports its screens; unknown ones become unassigned programs. */
    @PostMapping("/programs/sync")
    public Map<String, Object> sync(@RequestBody SyncRequest request) {
        int added = access.syncPrograms(request.programs() == null ? List.of() : request.programs());
        return Map.of("added", added, "unassigned", access.unassignedPrograms());
    }
}
