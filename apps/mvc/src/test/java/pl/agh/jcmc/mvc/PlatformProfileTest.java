package pl.agh.jcmc.mvc;

import static org.assertj.core.api.Assertions.assertThat;
import static pl.agh.jcmc.mvc.HttpTestSupport.get;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"app.io-delay-ms=100", "app.bcrypt-cost=4"})
@ActiveProfiles("platform")
class PlatformProfileTest {

    static final StubUpstream UPSTREAM = StubUpstream.start();

    @DynamicPropertySource
    static void upstream(DynamicPropertyRegistry registry) {
        registry.add("app.upstream-url", UPSTREAM::url);
    }

    @LocalServerPort
    int port;

    @Test
    void ioCallsUpstreamWithConfiguredDelay() {
        long start = System.nanoTime();
        ResponseEntity<String> response = get(port, "/io");
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody()).isEqualTo("{\"upstreamDelayMs\":100}");
        assertThat(elapsedMs).isGreaterThanOrEqualTo(100);
    }

    @Test
    void cpuVerifiesBcryptHash() {
        ResponseEntity<String> response = get(port, "/cpu");

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody()).isEqualTo("{\"matches\":true}");
    }

    @Test
    void requestsRunOnTomcatPlatformThreads() {
        String body = get(port, "/diag/thread").getBody();

        assertThat(body).contains("\"virtual\":false").contains("http-nio-");
    }

    @Test
    void exposesPrometheusMetricsWithModelTag() {
        get(port, "/cpu");
        String body = get(port, "/actuator/prometheus").getBody();

        assertThat(body)
                .contains("tomcat_threads_busy_threads")
                .contains("http_server_requests_seconds_count")
                .contains("model=\"platform\"");
    }

    @Test
    void healthIsUp() {
        assertThat(get(port, "/actuator/health").getBody()).contains("\"UP\"");
    }
}
