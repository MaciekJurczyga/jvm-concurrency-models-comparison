package pl.agh.jcmc.webflux;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.client.reactive.JdkClientHttpConnector;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"app.io-delay-ms=1000", "app.upstream-timeout=300ms", "app.bcrypt-cost=4"})
class UpstreamFailureTest {

    static final StubUpstream UPSTREAM = StubUpstream.start();

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

    @AfterEach
    void reset() {
        UPSTREAM.failing(false);
    }

    @Test
    void upstreamTimeoutMapsTo504() {
        long start = System.nanoTime();

        client.get().uri("/io").exchange()
                .expectStatus().isEqualTo(504)
                .expectBody(String.class).isEqualTo("{\"error\":\"upstream_timeout\"}");

        assertThat((System.nanoTime() - start) / 1_000_000).isLessThan(1000);
    }

    @Test
    void upstreamErrorMapsTo502() {
        UPSTREAM.failing(true);

        client.get().uri("/io").exchange()
                .expectStatus().isEqualTo(502)
                .expectBody(String.class).isEqualTo("{\"error\":\"upstream_error\"}");
    }
}
