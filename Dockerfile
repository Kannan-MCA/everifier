# Use an official OpenJDK 8 runtime as base image
FROM openjdk:8-jdk-alpine

# Set working directory
WORKDIR /app

# Copy Spring Boot executable jar file
COPY target/everifier-0.0.1-SNAPSHOT.jar app.jar

# (Optional) Copy logback configuration file separately, if not packaged inside jar
# COPY src/main/resources/logback-spring.xml ./config/logback-spring.xml

# Expose application port
EXPOSE 8081

# Run the jar with explicit logback configuration path if copied separately
ENTRYPOINT ["java", "-Dlogging.config=./config/logback-spring.xml", "-jar", "app.jar"]
