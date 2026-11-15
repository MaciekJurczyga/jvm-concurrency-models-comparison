package pl.agh.jcmc.mvc;

import static org.assertj.core.api.Assertions.assertThat;
import static pl.agh.jcmc.mvc.HttpTestSupport.get;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"app.io-delay-ms=1000", "app.upstream-timeout=300ms", "app.bcrypt-cost=4"})
@ActiveProfiles("platform")
class UpstreamFailureTest {

    static final StubUpstream UPSTREAM = StubUpstream.start();

    @DynamicPropertySource
    static void upstream(DynamicPropertyRegistry registry) {
        registry.add("app.upstream-url", UPSTREAM::url);
    }

    @LocalServerPort
    int port;

    @AfterEach
    void reset() {
        UPSTREAM.failing(false);
    }

    @Test
    void upstreamTimeoutMapsTo504() {
        long start = System.nanoTime();
        ResponseEntity<String> response = get(port, "/io");
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        assertThat(response.getStatusCode().value()).isEqualTo(504);
        assertThat(response.getBody()).isEqualTo("{\"error\":\"upstream_timeout\"}");
        assertThat(elapsedMs).isLessThan(1000);
    }

    @Test
    void upstreamErrorMapsTo502() {
        UPSTREAM.failing(true);

        ResponseEntity<String> response = get(port, "/io");

        assertThat(response.getStatusCode().value()).isEqualTo(502);
        assertThat(response.getBody()).isEqualTo("{\"error\":\"upstream_error\"}");
    }
}
