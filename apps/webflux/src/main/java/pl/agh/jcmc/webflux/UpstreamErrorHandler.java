package pl.agh.jcmc.webflux;

import java.net.SocketTimeoutException;
import java.util.concurrent.TimeoutException;

import io.netty.channel.ConnectTimeoutException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.reactive.function.client.WebClientException;

// Same mapping and bodies as MVC: 504 for dependency timeouts, 502 otherwise (DECISIONS.md, D10).
@RestControllerAdvice
class UpstreamErrorHandler {

    record ErrorResponse(String error) {
    }

    @ExceptionHandler(WebClientException.class)
    ResponseEntity<ErrorResponse> upstreamFailure(WebClientException ex) {
        if (isTimeout(ex)) {
            return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(new ErrorResponse("upstream_timeout"));
        }
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(new ErrorResponse("upstream_error"));
    }

    // Response timeout -> Netty ReadTimeoutException, connect timeout -> ConnectTimeoutException,
    // pool acquire timeout -> PoolAcquireTimeoutException (a java.util.concurrent.TimeoutException).
    private static boolean isTimeout(Throwable ex) {
        for (Throwable t = ex; t != null; t = t.getCause()) {
            if (t instanceof io.netty.handler.timeout.TimeoutException
                    || t instanceof ConnectTimeoutException
                    || t instanceof TimeoutException
                    || t instanceof SocketTimeoutException) {
                return true;
            }
        }
        return false;
    }
}
