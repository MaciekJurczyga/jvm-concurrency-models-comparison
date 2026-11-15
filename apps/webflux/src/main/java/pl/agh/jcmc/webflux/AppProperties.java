package pl.agh.jcmc.webflux;

import java.net.URI;
import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("app")
record AppProperties(URI upstreamUrl, long ioDelayMs, Duration upstreamTimeout, int bcryptCost,
                     int upstreamMaxConnections) {
}
