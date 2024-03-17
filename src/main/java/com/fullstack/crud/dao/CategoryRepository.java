package com.fullstack.crud.dao;

import com.fullstack.crud.entity.Task;
import com.fullstack.crud.entity.TaskCategory;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
@Repository
public interface CategoryRepository extends JpaRepository<TaskCategory, Integer> {
}
