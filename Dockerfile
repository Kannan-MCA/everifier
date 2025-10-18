# Use Java 8 base image
FROM openjdk:8-jdk-alpine

# Set working directory
WORKDIR /app

# Copy the built jar file into the container
COPY target/everifier-0.0.1-SNAPSHOT.jar app.jar

# Expose Spring Boot default port
EXPOSE 8081

# Run the application
ENTRYPOINT ["java", "-jar", "/app/app.jar"]