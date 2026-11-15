# syntax=docker/dockerfile:1
# Shared image recipe for every app module: docker build --build-arg MODULE=<fake-api|mvc|webflux> .
# Same JDK/JRE tags and JVM flags for all apps (DECISIONS.md, D4-D5).

FROM eclipse-temurin:25.0.5_8-jdk AS build
ARG MODULE
WORKDIR /src
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
COPY apps/ apps/
RUN --mount=type=cache,target=/root/.m2 \
    chmod +x mvnw && ./mvnw -B -q -pl apps/${MODULE} -am package -DskipTests

FROM eclipse-temurin:25.0.5_8-jre
ARG MODULE
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /src/apps/${MODULE}/target/app.jar app.jar

# G1 is forced explicitly: with <2 CPUs or <1792 MB the JVM silently falls back to SerialGC,
# which would differ between containers with different limits (DECISIONS.md, D5).
ENV JVM_BASE_OPTS="-XX:+UseG1GC -XX:MaxRAMPercentage=75"
# Per-run extras, e.g. -XX:+ExitOnOutOfMemoryError (open decision, DECISIONS.md, D6).
ENV JAVA_OPTS=""

EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec java $JVM_BASE_OPTS $JAVA_OPTS -jar /app/app.jar"]
