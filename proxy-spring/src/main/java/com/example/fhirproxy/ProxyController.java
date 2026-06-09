package com.example.fhirproxy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Base64;

@RestController
public class ProxyController {

    private static final String ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
    private static final String INFOMANIAK_URL = "https://api.infomaniak.com/2/ai/%s/openai/v1/chat/completions";

    @Value("${ANTHROPIC_API_KEY:}")
    private String anthropicApiKey;

    @Value("${INFOMANIAK_API_KEY:}")
    private String infomaniakApiKey;

    @Value("${INFOMANIAK_PRODUCT_ID:}")
    private String infomaniakProductId;

    @Autowired
    private FhirValidationService validationService;

    @Autowired
    private DoclingService doclingService;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final HttpClient httpClient = HttpClient.newHttpClient();

    @GetMapping("/prompt")
    public ResponseEntity<String> getPrompt() throws IOException {
        String template = Files.readString(Path.of("prompts", "system_prompt.txt"));
        String example = Files.readString(Path.of("prompts", "example_bundle.json")).trim();
        String prompt = template.replace("{EXAMPLE_BUNDLE}", example);
        return ResponseEntity.ok()
                .contentType(new MediaType("text", "plain", StandardCharsets.UTF_8))
                .body(prompt);
    }

    @PostMapping("/validate")
    public ResponseEntity<String> validate(HttpServletRequest request) throws IOException {
        byte[] body = request.getInputStream().readAllBytes();
        String outcome = validationService.validate(new String(body, StandardCharsets.UTF_8));
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_JSON)
                .body(outcome);
    }

    private static final DateTimeFormatter TIMESTAMP_FMT =
            DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss");

    @PostMapping("/**")
    public ResponseEntity<StreamingResponseBody> proxy(HttpServletRequest request)
            throws IOException, InterruptedException {
        byte[] body = request.getInputStream().readAllBytes();
        byte[] processedBody = replaceDocumentsWithMarkdown(body);
        logPrompt(processedBody);
        return isInfomaniakModel(extractModel(body))
                ? proxyInfomaniak(processedBody)
                : proxyAnthropic(processedBody);
    }

    private void logPrompt(byte[] promptBody) {
        String filename = "prompt_" + LocalDateTime.now().format(TIMESTAMP_FMT) + ".txt";
        try {
            Files.writeString(Path.of(filename),
                    new String(promptBody, StandardCharsets.UTF_8));
        } catch (IOException e) {
            // non-fatal – don't break the request if logging fails
        }
    }

    // ── OCR pre-processing ────────────────────────────────────────────────────

    private byte[] replaceDocumentsWithMarkdown(byte[] body) throws IOException {
        JsonNode root = objectMapper.readTree(body);

        boolean hasDocuments = false;
        for (JsonNode msg : root.path("messages")) {
            for (JsonNode item : msg.path("content")) {
                if ("document".equals(item.path("type").asText())) {
                    hasDocuments = true;
                    break;
                }
            }
        }
        if (!hasDocuments) return body;

        ObjectNode mutableRoot = root.deepCopy();
        ArrayNode messages = (ArrayNode) mutableRoot.path("messages");
        for (int i = 0; i < messages.size(); i++) {
            ObjectNode msg = (ObjectNode) messages.get(i);
            JsonNode content = msg.path("content");
            if (!content.isArray()) continue;

            ArrayNode newContent = objectMapper.createArrayNode();
            for (JsonNode item : content) {
                if ("document".equals(item.path("type").asText())) {
                    byte[] pdfBytes = Base64.getDecoder().decode(
                            item.path("source").path("data").asText());
                    String markdown = doclingService.convertPdfToMarkdown(pdfBytes);
                    ObjectNode textBlock = objectMapper.createObjectNode();
                    textBlock.put("type", "text");
                    textBlock.put("text", markdown);
                    newContent.add(textBlock);
                } else {
                    newContent.add(item);
                }
            }
            msg.set("content", newContent);
        }
        return objectMapper.writeValueAsBytes(mutableRoot);
    }

    // ── Anthropic ─────────────────────────────────────────────────────────────

    private ResponseEntity<StreamingResponseBody> proxyAnthropic(byte[] body)
            throws IOException, InterruptedException {
        HttpRequest upstream = HttpRequest.newBuilder()
                .uri(URI.create(ANTHROPIC_URL))
                .header("x-api-key", anthropicApiKey)
                .header("anthropic-version", "2023-06-01")
                .header("content-type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();

        HttpResponse<InputStream> response = httpClient.send(upstream, HttpResponse.BodyHandlers.ofInputStream());
        String contentType = response.headers().firstValue("content-type").orElse("application/json");

        StreamingResponseBody streaming = out -> {
            try (InputStream in = response.body()) { in.transferTo(out); }
        };

        return ResponseEntity.status(response.statusCode())
                .header(HttpHeaders.CONTENT_TYPE, contentType)
                .body(streaming);
    }

    // ── Infomaniak ────────────────────────────────────────────────────────────

    private ResponseEntity<StreamingResponseBody> proxyInfomaniak(byte[] anthropicBody)
            throws IOException, InterruptedException {

        if (infomaniakApiKey.isBlank() || infomaniakProductId.isBlank()) {
            byte[] err = "{\"error\":{\"message\":\"INFOMANIAK_API_KEY or INFOMANIAK_PRODUCT_ID not configured\"}}".getBytes(StandardCharsets.UTF_8);
            return ResponseEntity.status(500)
                    .header(HttpHeaders.CONTENT_TYPE, "application/json")
                    .body(out -> out.write(err));
        }

        byte[] openaiBody = transformToOpenAI(anthropicBody);
        String url = String.format(INFOMANIAK_URL, infomaniakProductId);

        HttpRequest upstream = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Authorization", "Bearer " + infomaniakApiKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(openaiBody))
                .build();

        HttpResponse<byte[]> response = httpClient.send(upstream, HttpResponse.BodyHandlers.ofByteArray());

        byte[] responseBody = response.statusCode() == 200
                ? transformFromOpenAI(response.body())
                : response.body();

        return ResponseEntity.status(response.statusCode())
                .header(HttpHeaders.CONTENT_TYPE, "application/json")
                .body(out -> out.write(responseBody));
    }

    // ── Format transformation ─────────────────────────────────────────────────

    private byte[] transformToOpenAI(byte[] anthropicBody) throws IOException {
        JsonNode src = objectMapper.readTree(anthropicBody);
        ObjectNode openai = objectMapper.createObjectNode();

        openai.put("model", src.path("model").asText());
        openai.put("max_tokens", src.path("max_tokens").asInt(4096));

        ArrayNode messages = objectMapper.createArrayNode();

        String system = src.path("system").asText(null);
        if (system != null && !system.isBlank()) {
            ObjectNode sysMsg = objectMapper.createObjectNode();
            sysMsg.put("role", "system");
            sysMsg.put("content", system);
            messages.add(sysMsg);
        }

        for (JsonNode msg : src.path("messages")) {
            ObjectNode newMsg = objectMapper.createObjectNode();
            newMsg.put("role", msg.path("role").asText());

            JsonNode content = msg.path("content");
            if (content.isArray()) {
                ArrayNode newContent = objectMapper.createArrayNode();
                for (JsonNode item : content) {
                    if ("text".equals(item.path("type").asText())) {
                        ObjectNode textItem = objectMapper.createObjectNode();
                        textItem.put("type", "text");
                        textItem.put("text", item.path("text").asText());
                        newContent.add(textItem);
                    }
                }
                newMsg.set("content", newContent);
            } else {
                newMsg.put("content", content.asText());
            }
            messages.add(newMsg);
        }

        openai.set("messages", messages);
        return objectMapper.writeValueAsBytes(openai);
    }

    private byte[] transformFromOpenAI(byte[] openaiBody) throws IOException {
        JsonNode src = objectMapper.readTree(openaiBody);

        ObjectNode anthropic = objectMapper.createObjectNode();
        anthropic.put("type", "message");
        anthropic.put("role", "assistant");

        String text = src.path("choices").path(0).path("message").path("content").asText("");
        ArrayNode content = objectMapper.createArrayNode();
        ObjectNode textBlock = objectMapper.createObjectNode();
        textBlock.put("type", "text");
        textBlock.put("text", text);
        content.add(textBlock);
        anthropic.set("content", content);
        anthropic.put("stop_reason", "end_turn");

        return objectMapper.writeValueAsBytes(anthropic);
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private String extractModel(byte[] body) {
        try {
            return objectMapper.readTree(body).path("model").asText(null);
        } catch (Exception e) {
            return null;
        }
    }

    private boolean isInfomaniakModel(String model) {
        return model != null && !model.startsWith("claude");
    }
}
