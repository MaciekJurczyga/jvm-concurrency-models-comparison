package pl.agh.jcmc.webflux;

import io.netty.channel.ChannelOption;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.ReactorResourceFactory;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.HttpProtocol;
import reactor.netty.http.client.HttpClient;
import reactor.netty.resources.ConnectionProvider;

@Configuration(proxyBeanMethods = false)
class UpstreamClientConfig {

    // The default Reactor Netty pool allows max(2 x CPUs, 16) connections, i.e. 16 in a 4-CPU container,
    // which would cap /io concurrency far below MVC's unbounded JDK client. Pool size, unbounded pending
    // queue, timeouts and HTTP/1.1 mirror the MVC client (DECISIONS.md, D7, D12).
    // runOn(...) shares the server's event loop, as Boot's auto-configured WebClient would; otherwise the
    // client gets a second, global loop and the SUT runs twice as many event-loop threads (DECISIONS.md, D14).
    @Bean
    WebClient upstreamWebClient(AppProperties props, ReactorResourceFactory resources) {
        ConnectionProvider pool = ConnectionProvider.builder("fake-api")
                .maxConnections(props.upstreamMaxConnections())
                .pendingAcquireMaxCount(-1)
                .pendingAcquireTimeout(props.upstreamTimeout())
                .build();
        HttpClient httpClient = HttpClient.create(pool)
                .runOn(resources.getLoopResources())
                .protocol(HttpProtocol.HTTP11)
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, (int) props.upstreamTimeout().toMillis())
                .responseTimeout(props.upstreamTimeout());
        return WebClient.builder()
                .baseUrl(props.upstreamUrl().toString())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
