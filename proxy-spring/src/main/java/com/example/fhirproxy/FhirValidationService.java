package com.example.fhirproxy;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.validation.FhirValidator;
import ca.uhn.fhir.validation.ValidationResult;
import jakarta.annotation.PostConstruct;
import org.hl7.fhir.common.hapi.validation.support.CachingValidationSupport;
import org.hl7.fhir.common.hapi.validation.support.CommonCodeSystemsTerminologyService;
import ca.uhn.fhir.context.support.DefaultProfileValidationSupport;
import org.hl7.fhir.common.hapi.validation.support.InMemoryTerminologyServerValidationSupport;
import org.hl7.fhir.common.hapi.validation.support.PrePopulatedValidationSupport;
import org.hl7.fhir.common.hapi.validation.support.ValidationSupportChain;
import org.hl7.fhir.common.hapi.validation.validator.FhirInstanceValidator;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

@Component
public class FhirValidationService {

    private static final Logger log = LoggerFactory.getLogger(FhirValidationService.class);

    private final FhirContext fhirContext = FhirContext.forR4();
    private FhirValidator validator;

    @PostConstruct
    public void init() throws IOException {
        PrePopulatedValidationSupport customSupport = new PrePopulatedValidationSupport(fhirContext);

        Path profilesDir = Path.of("fhir-profiles");
        if (Files.isDirectory(profilesDir)) {
            try (var paths = Files.list(profilesDir)) {
                paths.filter(p -> p.toString().endsWith(".json"))
                     .forEach(p -> loadProfile(p, customSupport));
            }
        } else {
            log.warn("Verzeichnis fhir-profiles nicht gefunden – Validierung nur gegen Basis-R4");
        }

        ValidationSupportChain chain = new ValidationSupportChain(
                new DefaultProfileValidationSupport(fhirContext),
                customSupport,
                new InMemoryTerminologyServerValidationSupport(fhirContext),
                new CommonCodeSystemsTerminologyService(fhirContext)
        );

        FhirInstanceValidator instanceValidator = new FhirInstanceValidator(new CachingValidationSupport(chain));
        instanceValidator.setAnyExtensionsAllowed(true);

        validator = fhirContext.newValidator();
        validator.registerValidatorModule(instanceValidator);
        log.info("FHIR-Validator initialisiert");
    }

    private void loadProfile(Path path, PrePopulatedValidationSupport support) {
        try {
            String json = Files.readString(path);
            IBaseResource resource = fhirContext.newJsonParser().parseResource(json);
            switch (fhirContext.getResourceType(resource)) {
                case "StructureDefinition" -> support.addStructureDefinition(resource);
                case "CodeSystem"          -> support.addCodeSystem(resource);
                case "ValueSet"            -> support.addValueSet(resource);
                default -> log.warn("Unbekannter Ressourcentyp in {}, wird ignoriert", path.getFileName());
            }
            log.info("Profil geladen: {}", path.getFileName());
        } catch (IOException e) {
            log.warn("Profildatei {} konnte nicht gelesen werden: {}", path, e.getMessage());
        }
    }

    public String validate(String fhirJson) {
        ValidationResult result = validator.validateWithResult(fhirJson);
        return fhirContext.newJsonParser()
                .setPrettyPrint(true)
                .encodeResourceToString(result.toOperationOutcome());
    }
}
