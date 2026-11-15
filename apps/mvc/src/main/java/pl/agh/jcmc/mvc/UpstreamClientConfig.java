package pl.agh.jcmc.mvc;

import java.net.http.HttpClient;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration(proxyBeanMethods = false)
class UpstreamClientConfig {

    // Explicit JDK HttpClient: its connection pool has no per-host limit, unlike e.g. Apache HttpClient
    // defaults, so the client cannot become the bottleneck. HTTP/1.1 is forced to skip the h2c upgrade
    // attempt; WebFlux uses HTTP/1.1 to the fake API as well (DECISIONS.md, D7).
    @Bean
    RestClient upstreamRestClient(AppProperties props) {
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(props.upstreamTimeout())
                .build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(httpClient);
        factory.setReadTimeout(props.upstreamTimeout());
        return RestClient.builder().baseUrl(props.upstreamUrl().toString()).requestFactory(factory).build();
    }
}
