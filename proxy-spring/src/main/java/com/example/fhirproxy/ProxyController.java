package com.example.fhirproxy;

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

@RestController
public class ProxyController {

    private static final String ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";

    @Value("${ANTHROPIC_API_KEY:}")
    private String apiKey;

    @Autowired
    private FhirValidationService validationService;

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

    @PostMapping("/**")
    public ResponseEntity<StreamingResponseBody> proxy(HttpServletRequest request)
            throws IOException, InterruptedException {

        byte[] body = request.getInputStream().readAllBytes();

        HttpRequest upstream = HttpRequest.newBuilder()
                .uri(URI.create(ANTHROPIC_URL))
                .header("x-api-key", apiKey)
                .header("anthropic-version", "2023-06-01")
                .header("content-type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();

        HttpResponse<InputStream> response = httpClient.send(upstream, HttpResponse.BodyHandlers.ofInputStream());

        String contentType = response.headers()
                .firstValue("content-type")
                .orElse("application/json");

        StreamingResponseBody streaming = outputStream -> {
            try (InputStream in = response.body()) {
                in.transferTo(outputStream);
            }
        };

        return ResponseEntity.status(response.statusCode())
                .header(HttpHeaders.CONTENT_TYPE, contentType)
                .body(streaming);
    }
}
