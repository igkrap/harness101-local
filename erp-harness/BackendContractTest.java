package __PACKAGE__;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import tools.jackson.databind.json.JsonMapper;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.fail;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.request;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(classes = __APPLICATION__.class)
@AutoConfigureMockMvc
@ActiveProfiles("test")
class HarnessContractVerificationTest {

    @Autowired
    private MockMvc mockMvc;

    private final JsonMapper mapper = JsonMapper.builder().build();

    @Test
    void verifyContract() throws Exception {
        Map<String, Object> envelope = mapper.readValue(Files.readString(Path.of("/app/verification-contract.json")), Map.class);
        String nonce = (String) envelope.get("nonce");
        List<Map<String, Object>> criteria = (List<Map<String, Object>>) envelope.get("criteria");

        if (criteria == null || criteria.isEmpty()) {
            throw new RuntimeException("No criteria found in contract");
        }

        for (Map<String, Object> criterion : criteria) {
            String id = (String) criterion.get("id");
            Map<String, Object> check = (Map<String, Object>) criterion.get("check");

            try {
                String method = (String) check.get("method");
                String path = (String) check.get("path");
                int expectedStatus = (int) check.get("status");

                // Calls run as a signed-in workspace user with a CSRF token, the way the app calls its API.
                var builder = request(HttpMethod.valueOf(method), path).contentType(MediaType.APPLICATION_JSON)
                        .with(user("harness-verifier").authorities(
                                new org.springframework.security.core.authority.SimpleGrantedAuthority("workspace:admin")))
                        .with(csrf());
                if (check.containsKey("body")) {
                    builder.content(mapper.writeValueAsString(check.get("body")));
                }

                MvcResult result = mockMvc.perform(builder).andReturn();
                String responseBody = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
                int actualStatus = result.getResponse().getStatus();

                if (expectedStatus != actualStatus) {
                    // Tell the author exactly what the fixed check sent and why the server refused it.
                    String reason = result.getResponse().getErrorMessage();
                    Exception resolved = result.getResolvedException();
                    if (resolved instanceof org.springframework.web.bind.MethodArgumentNotValidException invalid) {
                        reason = "invalid fields " + invalid.getBindingResult().getFieldErrors().stream()
                                .map(error -> error.getField() + " (" + error.getDefaultMessage() + ")").toList();
                    } else if (resolved != null && resolved.getMessage() != null) {
                        reason = resolved.getMessage().substring(0, Math.min(300, resolved.getMessage().length()));
                    }
                    // The answer often hides the real cause (a catch-all message); the root exception names it,
                    // e.g. a NOT NULL or unique constraint of the table.
                    Throwable root = resolved;
                    while (root != null && root.getCause() != null && root.getCause() != root) root = root.getCause();
                    if (root != null && root != resolved && root.getMessage() != null) {
                        String cause = root.getMessage().replaceAll("\\s+", " ");
                        reason = (reason == null ? "" : reason) + " | root cause: " + cause.substring(0, Math.min(300, cause.length()));
                    }
                    String sent = check.containsKey("body") ? " with body " + mapper.writeValueAsString(check.get("body")) : "";
                    String detail = (reason != null && !reason.isBlank() ? " reason: " + reason : "")
                            + (responseBody.isBlank() ? "" : " response: " + responseBody.substring(0, Math.min(400, responseBody.length())));
                    assertEquals(expectedStatus, actualStatus, "Status mismatch for " + id + ": " + method + " " + path + sent
                            + " returned " + actualStatus + "." + detail
                            + (expectedStatus >= 400 && actualStatus < 400
                                ? " The API accepted a request it must refuse. The check is fixed; make the API answer " + expectedStatus
                                    + " for this request (validate the missing or blank required fields before saving)."
                                : expectedStatus < 400 && actualStatus >= 400
                                    ? " The check is fixed; make the API accept this request."
                                    : " The check is fixed; make the API answer " + expectedStatus + " for this request."));
                }

                if (check.containsKey("json_path")) {
                    List<?> paths = (List<?>) check.get("json_path");
                    Object actualValue = mapper.readValue(responseBody, Object.class);

                    for (Object segment : paths) {
                        if (actualValue instanceof Map<?, ?> map) {
                            if (map.containsKey(segment)) {
                                actualValue = map.get(segment);
                            } else {
                                throw new AssertionError("Path segment " + segment + " missing in map");
                            }
                        } else if (actualValue instanceof List<?> list && ("length".equals(segment) || "size".equals(segment))) {
                            actualValue = list.size();  // ["length"] reads a list's item count
                        } else if (actualValue instanceof List<?> list) {
                            if (!(segment instanceof Number)) {
                                throw new AssertionError("List index must be a number (or \"length\"), got " + segment);
                            }
                            int idx = ((Number) segment).intValue();
                            if (idx >= 0 && idx < list.size()) {
                                actualValue = list.get(idx);
                            } else {
                                throw new AssertionError("Index " + segment + " out of bounds");
                            }
                        } else {
                            throw new AssertionError("Cannot traverse non-container type");
                        }
                    }

                    Object expectedValue = check.get("equals");
                    if (!Objects.deepEquals(actualValue, expectedValue)) {
                        throw new AssertionError("Value mismatch. Expected: " + expectedValue + " Actual: " + actualValue);
                    }
                }

                System.out.println(nonce + "|" + b64(id) + "|passed|" + b64(truncate("status=" + actualStatus + " body=" + responseBody)));

            } catch (Throwable t) {
                System.out.println(nonce + "|" + b64(id) + "|failed|" + b64(t.toString()));
            }
        }
    }

    private String b64(String input) {
        return Base64.getEncoder().encodeToString(input.getBytes(StandardCharsets.UTF_8));
    }

    private String truncate(String input) {
        return input.length() > 2000 ? input.substring(0, 2000) : input;
    }
}
