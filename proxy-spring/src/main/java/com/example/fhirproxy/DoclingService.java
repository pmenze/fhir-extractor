package com.example.fhirproxy;

import ai.docling.serve.api.convert.request.ConvertDocumentRequest;
import ai.docling.serve.api.convert.request.options.ConvertDocumentOptions;
import ai.docling.serve.api.convert.request.source.FileSource;
import ai.docling.serve.api.convert.response.ConvertDocumentResponse;
import ai.docling.serve.api.convert.response.InBodyConvertDocumentResponse;
import io.arconia.docling.client.DoclingServeClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Base64;

@Service
public class DoclingService {

    @Autowired
    private DoclingServeClient doclingClient;

    public String convertPdfToMarkdown(byte[] pdfBytes) {
        ConvertDocumentRequest request = ConvertDocumentRequest.builder()
                .source(FileSource.builder()
                        .filename("document.pdf")
                        .base64String(Base64.getEncoder().encodeToString(pdfBytes))
                        .build())
                .options(ConvertDocumentOptions.builder()
                        .doOcr(true)
                        .build())
                .build();

        ConvertDocumentResponse response = doclingClient.convertSource(request);
        InBodyConvertDocumentResponse inBody = (InBodyConvertDocumentResponse) response;
        String markdown = inBody.getDocument().getMarkdownContent();
        return markdown != null ? markdown : inBody.getDocument().getTextContent();
    }
}
