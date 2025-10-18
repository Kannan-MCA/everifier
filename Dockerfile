# Use Java 8 base image
FROM openjdk:8-jdk-alpine

# Set working directory
WORKDIR /app

# Copy the built jar file into the container
COPY target/everifier-0.0.1-SNAPSHOT.jar app.jar

<<<<<<< HEAD
# Expose Spring Boot default port
=======
# Copy the JKS keystore file into the container
COPY src/main/resources/yourkeystore.jks /app/yourkeystore.jks

# Expose Spring Boot port
>>>>>>> daf88c3d972d0d1b9919a93f3142665a44e3fcbe
EXPOSE 8081

# Run the application
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
