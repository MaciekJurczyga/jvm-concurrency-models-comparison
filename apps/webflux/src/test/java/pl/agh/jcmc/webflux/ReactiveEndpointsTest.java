package pl.agh.jcmc.webflux;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.client.reactive.JdkClientHttpConnector;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

// Runs with BlockHound installed (blockhound-junit-platform): a blocking call on an event-loop or
// parallel thread would fail the request with 500 and thus the test.
// The test client uses the JDK connector so that it creates no Reactor Netty threads of its own.
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"app.io-delay-ms=100", "app.bcrypt-cost=4"})
class ReactiveEndpointsTest {

    static final StubUpstream UPSTREAM = StubUpstream.start();
    static final Pattern EVENT_LOOP_THREAD = Pattern.compile("([a-z]+-http-(?:nio|epoll))-\\d+");

    @DynamicPropertySource
    static void upstream(DynamicPropertyRegistry registry) {
        registry.add("app.upstream-url", UPSTREAM::url);
    }

    @LocalServerPort
    int port;

    WebTestClient client;

    @BeforeEach
    void client() {
        client = WebTestClient.bindToServer(new JdkClientHttpConnector()).baseUrl("http://localhost:" + port)
                .responseTimeout(Duration.ofSeconds(10)).build();
    }

    @Test
    void ioCallsUpstreamWithConfiguredDelay() {
        long start = System.nanoTime();

        client.get().uri("/io").exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("{\"upstreamDelayMs\":100}");

        assertThat((System.nanoTime() - start) / 1_000_000).isGreaterThanOrEqualTo(100);
    }

    @Test
    void cpuVerifiesBcryptHash() {
        client.get().uri("/cpu").exchange()
                .expectStatus().isOk()
                .expectBody(String.class).isEqualTo("{\"matches\":true}");
    }

    @Test
    void requestsRunOnNettyEventLoop() {
        client.get().uri("/diag/thread").exchange()
                .expectStatus().isOk()
                .expectBody(String.class).value(body -> assertThat(body)
                        .contains("\"virtual\":false").containsPattern(EVENT_LOOP_THREAD.pattern()));
    }

    // Thread prefix depends on platform and resource setup (webflux-http-nio on Windows tests,
    // reactor-http-epoll in the Linux container); there must be exactly one event-loop group.
    @Test
    void upstreamClientSharesServerEventLoop() {
        client.get().uri("/io").exchange().expectStatus().isOk();

        Set<String> eventLoopGroups = Thread.getAllStackTraces().keySet().stream()
                .map(Thread::getName)
                .map(EVENT_LOOP_THREAD::matcher)
                .filter(Matcher::matches)
                .map(m -> m.group(1))
                .collect(Collectors.toSet());

        assertThat(eventLoopGroups).hasSize(1);
    }

    @Test
    void exposesPrometheusMetricsWithModelTag() {
        client.get().uri("/cpu").exchange().expectStatus().isOk();

        client.get().uri("/actuator/prometheus").exchange()
                .expectStatus().isOk()
                .expectBody(String.class).value(body -> assertThat(body)
                        .contains("http_server_requests_seconds_count")
                        .contains("http_server_requests_active_seconds_count")
                        .contains("model=\"reactive\""));
    }

    @Test
    void healthIsUp() {
        client.get().uri("/actuator/health").exchange()
                .expectStatus().isOk()
                .expectBody(String.class).value(body -> assertThat(body).contains("\"UP\""));
    }
}
